"""Display times and labels never rewrite stored evidence."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import Settings
from src.domain.diary import DiaryConfirmation, DiaryEvent
from src.domain.models import (
    AssessmentMode,
    AuditEvent,
    ConfidenceTier,
    DraftSource,
    GateDecision,
    OwnerDecision,
)
from src.domain.presentation import (
    assessment_result_label,
    assessment_source_label,
    event_display_label,
    format_display_time,
    gate_result_label,
    owner_choice_label,
    owner_outcome_label,
    short_evidence_reference,
)
from src.runtime.daily_diary import run_daily_diary
from src.tools import audit
from src.tools.diary import confirm_diary
from src.tools.export import export_evidence
from tests.audit_support import NOW
from tests.test_api import post, start
from tests.test_diary import decision_entry

ISO_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T")
HASH_ID = re.compile(r"[0-9a-f]{64}")
GREEN_EXPORT = (
    "#216e59",
    "#f3f5ee",
    "#183c34",
    "#709b86",
    "#eaf3eb",
    "#45655b",
    "#28a745",
)
MACHINE_MARKERS = (
    "Technical evidence",
    "Technical record",
    "Filed at (raw)",
    "As of (raw)",
    "(raw)",
    "#decision_recorded",
    "Evidence reference",
    "payload_json",
)


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"details", "pre", "script", "style"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"details", "pre", "script", "style"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self.parts.append(data)

    def text(self) -> str:
        return " ".join(part.strip() for part in self.parts if part.strip())


def visible_text(html: str) -> str:
    parser = _VisibleText()
    parser.feed(html)
    return parser.text()


def test_london_times_use_bst_and_gmt_without_seconds() -> None:
    bst = datetime.fromisoformat("2026-09-14T10:51:12.262112+00:00")
    gmt = datetime.fromisoformat("2026-01-14T10:51:00+00:00")
    assert format_display_time(bst) == "14 Sep 2026, 11:51 BST"
    assert format_display_time(gmt) == "14 Jan 2026, 10:51 GMT"


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        format_display_time(datetime(2026, 9, 14, 10, 51))


def test_short_reference_does_not_change_stored_identity() -> None:
    stored = "434f8d36f712efafb6cbc6cede73cd38ac3df81ade9b1123bfc8631bbfa74fc1#decision_recorded"
    assert short_evidence_reference(stored) == "434f8d36…74fc1"
    assert stored.endswith("#decision_recorded")


def test_event_labels_are_plain_english() -> None:
    assert event_display_label(AuditEvent.MATCH_DECISION) == "Assessment recorded"
    assert event_display_label(AuditEvent.ESCALATION_QUEUED) == "Escalation queued"
    assert event_display_label(AuditEvent.DECISION_RECORDED) == "Owner decision recorded"
    assert event_display_label(DiaryEvent.FILED) == "Daily diary filed"
    assert event_display_label(DiaryEvent.CONFIRMED) == "Diary confirmation recorded"
    assert assessment_result_label(ConfidenceTier.NO_MATCH) == "No recorded match"
    assert assessment_result_label(ConfidenceTier.POSSIBLE) == "Possible match"
    assert gate_result_label(GateDecision.SILENT) == "Handled quietly"
    assert gate_result_label(GateDecision.ESCALATE) == "Owner review required"
    assert assessment_source_label(AssessmentMode.INJECTED) == "Injected replay proposal"
    assert (
        assessment_source_label(AssessmentMode.BEDROCK, DraftSource.FALLBACK)
        == "Conservative fallback draft"
    )
    assert owner_choice_label(OwnerDecision.EDIT) == "Edit"
    assert owner_outcome_label(OwnerDecision.APPROVE) == "Approved"
    assert owner_outcome_label("decline") == "Declined"


def test_csv_and_html_are_readable_without_machine_payloads(
    audit_settings: Settings, tmp_path: Path
) -> None:
    entry = decision_entry()
    audit.append_audit_entry(entry, audit_settings)
    run_daily_diary("demo-cafe", NOW.date(), now=NOW, settings=audit_settings)
    confirm_diary(
        "demo-cafe",
        NOW.date(),
        DiaryConfirmation(opening_status="confirmed", closing_status="confirmed"),
        now=NOW,
        settings=audit_settings,
    )
    after_write = audit.list_history("demo-cafe", audit_settings)
    result = export_evidence(
        "demo-cafe",
        csv_path=tmp_path / "diary.csv",
        html_path=tmp_path / "diary.html",
        settings=audit_settings,
        as_of=NOW,
        storage_label="Offline simulated",
    )
    assert audit.list_history("demo-cafe", audit_settings) == after_write
    assert any(row.entry_id == entry.entry_id for row in after_write)
    with result.csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    csv_text = result.csv_path.read_text(encoding="utf-8-sig")
    assert "PUBLIC BROWSER SIMULATION" not in csv_text
    assert "payload_json" not in csv_text
    assert HASH_ID.search(csv_text) is None
    assert "T13:00" not in csv_text
    decision = next(row for row in rows if row["event_label"] == "Owner decision recorded")
    assert decision["display_time"] == "10 Sep 2026, 13:00 BST"
    assert decision["alert_title"] == entry.alert_title
    assert decision["owner_choice"] == "Approve"
    html = result.html_path.read_text(encoding="utf-8")
    visible = visible_text(html)
    assert "10 Sep 2026, 13:00 BST" in visible
    assert "Owner decision recorded" in visible
    assert "Approved" in html
    assert "<pre" not in html
    assert ISO_STAMP.search(html) is None
    assert HASH_ID.search(html) is None
    for marker in MACHINE_MARKERS:
        assert marker not in html
    assert entry.entry_id not in html
    assert entry.timestamp.isoformat() not in html
    assert "append-only" in html.casefold()
    assert "tamper-proof" in html.casefold()
    assert "compliance certificate" in html.casefold()
    assert "#f4f1ea" in html
    assert "#2f4cb0" in html
    assert "#fffcf7" in html
    for token in GREEN_EXPORT:
        assert token not in html.casefold()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(origin="http://testserver")) as value:
        yield value


def test_dashboard_cards_hide_iso_and_full_ids(client: TestClient) -> None:
    start(client)
    assert post(client, "/demo/run").status_code == 200
    queued = client.get("/api/inbox").json()
    for row, choice in zip(queued, ("approve", "edit", "decline"), strict=True):
        payload: dict[str, object] = {"escalation_id": row["escalation_id"], "choice": choice}
        if choice == "edit":
            payload["pack"] = row["action_pack"]
        assert post(client, "/api/decisions", payload).status_code == 200
    assert post(client, "/api/diary/file").status_code == 200
    assert (
        post(
            client,
            "/api/diary/confirm",
            {"opening_status": "confirmed", "closing_status": "confirmed"},
        ).status_code
        == 200
    )
    links = client.get("/api/diary").json()["current_recall_actions"]
    assert len(links) == 3
    forbidden = (
        "Technical record",
        "Copy technical record",
        "View technical draft JSON",
        "Technical evidence",
        "payload_json",
    )
    for page in ("inbox", "audit", "diary", "business"):
        html = client.get("/" + page).text
        visible = visible_text(html)
        assert ISO_STAMP.search(visible) is None
        assert HASH_ID.search(visible) is None
        for marker in forbidden:
            assert marker not in html
        assert "<pre" not in html
        if page in {"audit", "diary", "business"}:
            assert HASH_ID.search(html) is None
        assert "Inspect stored evidence" in html or page != "audit"
    diary = client.get("/diary").text
    assert "View audit trail" in diary
    assert "View decision evidence" not in diary
    for link in links:
        assert link["event_id"] not in diary
        assert f'href="/audit#{link["event_id"]}"' not in diary
    csv_text = client.get("/exports/csv").content.decode("utf-8-sig")
    assert "PUBLIC BROWSER SIMULATION" not in csv_text
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert rows
    assert {"display_time", "event_label", "alert_reference", "owner_choice"} <= set(rows[0])
    assert "payload_json" not in rows[0]
    assert "event_id" not in rows[0]
    assert "raw_timestamp" not in rows[0]
    assert HASH_ID.search(csv_text) is None
    html_export = client.get("/exports/html").text
    assert "Recall audit events" in html_export
    assert html_export.count("<b>14</b>") >= 1
    assert "Distinct assessments" in html_export
    assert "Silent decision events" in html_export
    assert "Requires-review decision events" in html_export
    assert "Assessment error events" in html_export
    assert "Decision record filed" in html_export
    assert "Approved" in html_export
    assert "Edited" in html_export
    assert "Declined" in html_export
    assert "View decision evidence" in html_export
    assert "No customer notice or stock action was executed" in html_export
    assert ISO_STAMP.search(html_export) is None
    assert HASH_ID.search(html_export) is None
    assert "<pre" not in html_export
    for marker in MACHINE_MARKERS:
        assert marker not in html_export
    assert "#f4f1ea" in html_export
    assert "#2f4cb0" in html_export
    for token in GREEN_EXPORT:
        assert token not in html_export.casefold()
    assert links[0]["event_id"] not in html_export
    assert "#decision_recorded" not in html_export


def test_audit_inspector_is_readable_without_json_payload(client: TestClient) -> None:
    start(client)
    assert post(client, "/demo/run").status_code == 200
    queued = client.get("/api/inbox").json()
    for row, choice in zip(queued, ("approve", "edit", "decline"), strict=True):
        payload: dict[str, object] = {"escalation_id": row["escalation_id"], "choice": choice}
        if choice == "edit":
            payload["pack"] = row["action_pack"]
        assert post(client, "/api/decisions", payload).status_code == 200
    assert post(client, "/api/diary/file").status_code == 200
    assert (
        post(
            client,
            "/api/diary/confirm",
            {"opening_status": "confirmed", "closing_status": "confirmed"},
        ).status_code
        == 200
    )
    api_rows = client.get("/api/audit").json()
    html = client.get("/audit").text
    assert "No recorded match" in html
    assert "Handled quietly" in html
    assert "Owner review required" in html
    assert "Injected replay proposal" in html
    assert "Daily diary filing" in html
    assert "Diary confirmation" in html
    assert "Owner decision" in html
    assert "This records an owner choice. It does not execute stock or customer actions." in html
    assert "This event is retained in the append-only audit trail." in html
    assert "Technical record" not in html
    assert "Copy technical record" not in html
    assert "<pre" not in html
    assert HASH_ID.search(html) is None
    persisted = client.get("/api/audit").json()
    assert persisted == api_rows
    assert {row["event"] for row in persisted} >= {
        "match_decision",
        "decision_recorded",
        "diary_filed",
        "diary_confirmed",
    }


def test_edit_form_prefills_and_submits_action_pack_shape(client: TestClient) -> None:
    start(client)
    assert post(client, "/demo/run").status_code == 200
    queued = client.get("/api/inbox").json()
    inbox = client.get("/inbox").text
    script = Path("web/static/app.js").read_text(encoding="utf-8")
    assert "Review and edit draft" in inbox
    assert 'name="pack"' not in inbox
    assert "View technical draft JSON" not in inbox
    assert "<pre" not in inbox
    assert "JSON.parse" not in script
    assert "packFromForm" in script
    assert "data-cancel-edit" in inbox
    row = queued[0]
    pack = row["action_pack"]
    for field in ("pull", "staff_note", "customer_notice", "substitution"):
        assert f'name="{field}"' in inbox
        match = re.search(
            rf'id="[^"]*" name="{field}"[^>]*>(.*?)</textarea>',
            inbox,
            flags=re.S,
        )
        assert match is not None
        assert unescape(match.group(1)) == pack[field]
    edited = pack | {"staff_note": pack["staff_note"] + " (owner check)"}
    before = len(client.get("/api/audit").json())
    assert client.get("/inbox").status_code == 200
    assert len(client.get("/api/audit").json()) == before
    bad = pack | {"customer_notice": ""}
    assert (
        post(
            client,
            "/api/decisions",
            {"escalation_id": row["escalation_id"], "choice": "edit", "pack": bad},
        ).status_code
        == 422
    )
    assert len(client.get("/api/audit").json()) == before
    created = post(
        client,
        "/api/decisions",
        {"escalation_id": row["escalation_id"], "choice": "edit", "pack": edited},
    )
    assert created.status_code == 200
    retry = post(
        client,
        "/api/decisions",
        {"escalation_id": row["escalation_id"], "choice": "decline"},
    )
    assert retry.status_code == 200
    assert not retry.json()["created"]
    assert retry.json()["record"]["decision"] == "edit"
    decision = next(
        item for item in client.get("/api/audit").json() if item["event"] == "decision_recorded"
    )
    assert decision["owner_decision"]["original_action_pack"] == pack
    assert decision["owner_decision"]["edited_pack"] == edited
    assert set(decision["owner_decision"]["edited_pack"]) == {
        "pull",
        "staff_note",
        "customer_notice",
        "substitution",
    }
