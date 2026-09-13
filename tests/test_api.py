"""Browser boundary proofs over the real offline cycle and append-only store."""

import csv
import io
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from src.api.app import create_app
from src.tools.demo_sessions import DemoSessions


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(origin="http://testserver")) as value:
        yield value


def post(client: TestClient, path: str, payload: dict[str, object] | None = None) -> Response:
    return client.post(
        path,
        json=payload or {},
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": client.cookies.get("ag_csrf", ""),
        },
    )


def start(client: TestClient) -> None:
    assert client.get("/inbox").status_code == 200
    assert post(client, "/demo/session").status_code == 200


def test_reads_do_not_create_domain_records(client: TestClient) -> None:
    for page in ("inbox", "audit", "diary", "business"):
        assert client.get("/" + page).status_code == 200
    assert len(client.app.state.sessions.sessions) == 0
    start(client)
    assert client.get("/api/diary").json() is None
    assert client.get("/api/audit").json() == []


def test_full_browser_contract_and_replay(client: TestClient) -> None:
    start(client)
    result = post(client, "/demo/run")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "committed"
    queued = client.get("/api/inbox").json()
    assert len(queued) == 3
    assert len(client.get("/api/audit").json()) == 11
    for page in ("inbox", "audit", "diary", "business"):
        assert client.get("/" + page).status_code == 200
    audit = client.get("/audit").text
    assert audit.count('class="card silent-row"') == 2
    for row, choice in zip(queued, ("approve", "edit", "decline"), strict=True):
        payload = {"escalation_id": row["escalation_id"], "choice": choice}
        if choice == "edit":
            payload["pack"] = row["action_pack"]
        response = post(client, "/api/decisions", payload)
        assert response.status_code == 200, response.text
    assert client.get("/api/inbox").json() == []
    assert len(client.get("/api/audit").json()) == 14
    assert "Nothing needs your review right now" in client.get("/inbox").text
    assert post(client, "/demo/run").json()["status"] == "empty"
    assert len(client.get("/api/audit").json()) == 14
    assert post(client, "/api/diary/file").status_code == 200
    assert len(client.get("/api/audit").json()) == 15
    assert (
        post(
            client,
            "/api/diary/confirm",
            {
                "opening_status": "confirmed",
                "closing_status": "confirmed",
            },
        ).status_code
        == 200
    )
    before = client.get("/api/audit").json()
    assert len(before) == 16
    again = post(
        client,
        "/api/diary/confirm",
        {
            "opening_status": "exception",
            "closing_status": "confirmed",
            "note": "Test exception",
        },
    )
    assert again.json()["created"] is False
    assert client.get("/api/audit").json() == before
    view = client.get("/api/diary").json()
    assert view["confirmation"]["confirmation"]["mode"] == "simulated"
    assert len(view["current_recall_actions"]) == 3
    export = client.get("/exports/csv")
    assert len(list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig"))))) == 16
    assert client.get("/exports/html").status_code == 200
    assert client.get("/api/audit").json() == before


def test_isolated_sessions_and_fresh_ledger(client: TestClient) -> None:
    start(client)
    first = dict(client.cookies)
    post(client, "/demo/run")
    row = client.get("/api/inbox").json()[0]
    assert post(client, "/demo/session").status_code == 200
    assert client.get("/api/audit").json() == []
    assert (
        post(
            client,
            "/api/decisions",
            {
                "escalation_id": row["escalation_id"],
                "choice": "approve",
            },
        ).status_code
        == 422
    )
    assert post(client, "/demo/run").json()["status"] == "committed"
    assert (
        post(
            client,
            "/api/decisions",
            {
                "escalation_id": row["escalation_id"],
                "choice": "approve",
            },
        ).status_code
        == 200
    )
    client.cookies.clear()
    client.cookies.update(first)
    assert len(client.get("/api/inbox").json()) == 3
    assert len(client.get("/api/audit").json()) == 11


def test_invalid_inputs_and_first_choice(client: TestClient) -> None:
    start(client)
    post(client, "/demo/run")
    row = client.get("/api/inbox").json()[0]
    base = {"escalation_id": row["escalation_id"], "choice": "edit"}
    assert post(client, "/api/decisions", base).status_code == 422
    bad_pack = row["action_pack"] | {"customer_notice": ""}
    assert post(client, "/api/decisions", base | {"pack": bad_pack}).status_code == 422
    assert len(client.get("/api/audit").json()) == 11
    assert post(client, "/api/decisions", base | {"choice": "approve"}).json()["created"]
    retry = post(client, "/api/decisions", base | {"choice": "decline"})
    assert not retry.json()["created"]
    assert retry.json()["record"]["decision"] == "approve"
    assert post(client, "/api/diary/confirm", {}).status_code == 422
    assert (
        post(
            client,
            "/api/diary/confirm",
            {
                "opening_status": "exception",
                "closing_status": "confirmed",
            },
        ).status_code
        == 422
    )


def test_csrf_host_capacity_and_unknown_session(client: TestClient) -> None:
    start(client)
    assert client.post("/demo/run", json={}).status_code == 403
    assert (
        client.post(
            "/demo/run",
            json={},
            headers={
                "Origin": "https://other.test",
                "X-CSRF-Token": client.cookies["ag_csrf"],
            },
        ).status_code
        == 403
    )
    assert client.get("/inbox", headers={"Host": "evil.test"}).status_code == 400
    assert post(client, "/demo/run", {"junk": "x" * 17000}).status_code == 413
    client.cookies.clear()
    client.cookies.set("ag_session", "forged")
    assert client.get("/api/audit").status_code == 409


def test_bounded_capacity() -> None:
    with TestClient(
        create_app(origin="http://testserver", sessions=DemoSessions(limit=1))
    ) as client:
        start(client)
        assert post(client, "/demo/session").status_code == 429
        assert client.get("/api/audit").status_code == 200


def test_storage_failure_is_not_success(client: TestClient) -> None:
    start(client)
    with patch("src.runtime.cycle.alert_ledger.load_new_alerts", side_effect=RuntimeError):
        result = post(client, "/demo/run")
    assert result.status_code == 503
    assert result.json()["status"] == "blocked"


def test_concurrent_replay_is_serialized(client: TestClient) -> None:
    start(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: post(client, "/demo/run"), range(2)))
    assert {row.json()["status"] for row in results} == {"committed", "empty"}
    assert len(client.get("/api/audit").json()) == 11


def test_aws_evidence_mode_does_not_start_mock_or_allow_writes() -> None:
    manager = DemoSessions()
    manager.start()
    try:
        _, session = manager.create()
        with (
            patch.object(DemoSessions, "start", side_effect=AssertionError("No nested Moto")),
            TestClient(
                create_app(origin="http://testserver", aws_settings=session.settings)
            ) as client,
        ):
            assert client.get("/business").status_code == 200
            assert "AWS stored evidence" in client.get("/inbox").text
            for path in (
                "/demo/session",
                "/demo/run",
                "/api/decisions",
                "/api/diary/file",
                "/api/diary/confirm",
            ):
                assert client.post(path, json={}).status_code == 403
            assert client.get("/api/audit").json() == []
    finally:
        manager.close()


def test_owner_text_is_escaped(client: TestClient) -> None:
    start(client)
    post(client, "/api/diary/file")
    post(
        client,
        "/api/diary/confirm",
        {
            "opening_status": "exception",
            "closing_status": "confirmed",
            "note": '<script>alert("x")</script>',
        },
    )
    response = client.get("/diary")
    assert '<script>alert("x")</script>' not in response.text
    assert "&lt;script&gt;" in response.text
    assert "default-src 'self'" in response.headers["content-security-policy"]
