"""Server-rendered surface; trusted adapters own all domain operations."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config import Settings
from src.domain.diary import DiaryConfirmation, business_date
from src.domain.models import AuditEntry
from src.domain.presentation import (
    assessment_result_label,
    assessment_source_label,
    event_display_label,
    format_display_date,
    format_display_time,
    gate_result_label,
    owner_choice_label,
    short_evidence_reference,
)
from src.domain.surface import DecisionRequest
from src.runtime import surface
from src.tools import audit, inventory
from src.tools.demo_sessions import DemoSessions, SurfaceSession
from src.tools.escalation_queue import list_pending

logger = logging.getLogger(__name__)
WEB = Path(__file__).resolve().parents[2] / "web"
DEMO_LABEL = "Interactive replay demo · synthetic business · simulated notifications"
AWS_LABEL = "AWS stored evidence · read-only · no monitoring status inferred"


def safe_source(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme == "https" and parsed.hostname in {"www.food.gov.uk", "food.gov.uk"}:
        return value
    return None


def create_app(
    *,
    origin: str = "http://127.0.0.1:8000",
    sessions: DemoSessions | None = None,
    aws_settings: Settings | None = None,
    business_id: str = "demo-cafe",
) -> FastAPI:
    demo = aws_settings is None
    manager = sessions or DemoSessions()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if demo:
            manager.start()
        try:
            yield
        finally:
            if demo:
                manager.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.sessions = manager
    templates = Jinja2Templates(directory=str(WEB / "templates"))
    templates.env.filters["safe_source"] = safe_source
    templates.env.filters["display_time"] = format_display_time
    templates.env.filters["display_date"] = format_display_date
    templates.env.filters["event_label"] = event_display_label
    templates.env.filters["evidence_ref"] = short_evidence_reference
    templates.env.filters["assessment_result"] = assessment_result_label
    templates.env.filters["gate_result"] = gate_result_label
    templates.env.filters["assessment_source"] = assessment_source_label
    templates.env.filters["owner_choice"] = owner_choice_label
    app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")
    allowed_host = urlsplit(origin).netloc
    secure = urlsplit(origin).scheme == "https"

    @app.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        # Starlette's middleware callable is dynamically supplied by the framework.
        if request.headers.get("host") != allowed_host:
            return JSONResponse({"detail": "Unrecognized host."}, status_code=400)
        if request.method == "POST":
            if not demo:
                return JSONResponse({"detail": "Evidence mode is read-only."}, status_code=403)
            if request.headers.get("origin") != origin:
                return JSONResponse({"detail": "Same-origin request required."}, status_code=403)
            cookie = request.cookies.get("ag_csrf", "")
            token = request.headers.get("x-csrf-token", "")
            if (
                not cookie
                or not cookie.isascii()
                or not token.isascii()
                or not compare_digest(cookie, token)
            ):
                return JSONResponse(
                    {"detail": "Refresh this page before submitting."}, status_code=403
                )
            existing = manager.get(request.cookies.get("ag_session"))
            if existing and not compare_digest(existing.csrf, token):
                return JSONResponse({"detail": "Session token mismatch."}, status_code=403)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16384:
                    return JSONResponse({"detail": "Request is too large."}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            {"detail": "Check the required fields and valid choices."}, status_code=422
        )

    @app.exception_handler(Exception)
    async def operation_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("surface_operation_failed type=%s", type(exc).__name__)
        return JSONResponse(
            {"detail": "Operation could not be acknowledged. Refresh and retry the same action."},
            status_code=503,
        )

    def current(request: Request) -> SurfaceSession:
        if demo:
            session = manager.get(request.cookies.get("ag_session"))
            if session is None:
                raise HTTPException(409, "Start a fresh demo; this session is missing or expired.")
            return session
        assert aws_settings is not None
        business = inventory.read_business(business_id, aws_settings)
        if business is None:
            raise HTTPException(404, "Configured business not found.")
        return SurfaceSession(aws_settings, business)

    def maybe_current(request: Request) -> SurfaceSession | None:
        return manager.get(request.cookies.get("ag_session")) if demo else current(request)

    @app.get("/")
    def home() -> RedirectResponse:
        return RedirectResponse("/inbox", status_code=303)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready", "mode": "demo" if demo else "aws-evidence"}

    @app.get("/{page}", response_class=HTMLResponse)
    def page_view(request: Request, page: str) -> Response:
        if page not in {"inbox", "audit", "diary", "business"}:
            raise HTTPException(404, "Page not found.")
        session = maybe_current(request)
        csrf = session.csrf if session else request.cookies.get("ag_csrf") or token_urlsafe(32)
        # Template context contains heterogeneous typed model instances.
        context: dict[str, Any] = {
            "page": page,
            "csrf": csrf,
            "demo": demo,
            "session": session,
            "label": DEMO_LABEL if demo else AWS_LABEL,
            "pending": [],
            "rows": [],
            "diary": None,
            "day": business_date(datetime.now(UTC)),
            "assessed": 0,
            "silent": 0,
        }
        if session:
            with session.lock:
                rows = audit.list_history(session.business.business_id, session.settings)
                pending = list_pending(session.business.business_id, session.settings)
                recalls = [row for row in rows if isinstance(row, AuditEntry)]
                context.update(
                    {
                        "rows": rows,
                        "pending": pending,
                        "assessed": len({row.assessment_id for row in recalls}),
                        "silent": sum(
                            row.event.value == "match_decision" and row.decision.value == "silent"
                            for row in recalls
                        ),
                        "diary": surface.diary(session) if page == "diary" else None,
                    }
                )
        response = templates.TemplateResponse(
            request=request,
            name=page + ".html",
            context=context,
        )
        response.set_cookie("ag_csrf", csrf, httponly=True, samesite="strict", secure=secure)
        return response

    @app.post("/demo/session")
    def new_session() -> JSONResponse:
        try:
            identity, session = manager.create()
        except RuntimeError as error:
            raise HTTPException(429, str(error)) from error
        response = JSONResponse({"message": "Fresh isolated demo ready."})
        response.set_cookie("ag_session", identity, httponly=True, samesite="strict", secure=secure)
        response.set_cookie(
            "ag_csrf", session.csrf, httponly=True, samesite="strict", secure=secure
        )
        return response

    @app.post("/demo/run")
    def run_demo(request: Request) -> JSONResponse:
        session = current(request)
        with session.lock:
            surface.cycle(session)
            assert session.last_cycle is not None
            report = session.last_cycle
            ok = report.status.value in {"committed", "empty"}
            return JSONResponse(report.model_dump(mode="json"), status_code=200 if ok else 503)

    @app.post("/api/decisions")
    def decision(request: Request, payload: DecisionRequest) -> JSONResponse:
        session = current(request)
        with session.lock:
            try:
                result = surface.decide(
                    session,
                    payload.escalation_id,
                    payload.choice,
                    payload.pack,
                )
            except ValueError as error:
                raise HTTPException(
                    422, "Invalid choice, draft, or escalation identity."
                ) from error
            return JSONResponse(
                {
                    "message": f"Stored choice: {result.record.decision.value}. "
                    "No stock or customer action executed.",
                    "created": result.created,
                    "record": result.record.model_dump(mode="json"),
                }
            )

    @app.post("/api/diary/file")
    def file_daily(request: Request) -> dict[str, str]:
        session = current(request)
        with session.lock:
            surface.file_diary(session)
        return {"message": "Diary filed or reused. Opening and closing await explicit answers."}

    @app.post("/api/diary/confirm")
    def confirm_daily(request: Request, payload: DiaryConfirmation) -> dict[str, object]:
        session = current(request)
        with session.lock:
            try:
                created = surface.confirm(session, payload)
            except ValueError as error:
                raise HTTPException(
                    422, "Prepare the diary and check your explicit answers."
                ) from error
        return {
            "message": "Stored first confirmation retained. No physical action executed.",
            "created": created,
        }

    @app.get("/api/inbox")
    def inbox_data(request: Request) -> list[dict[str, Any]]:
        # JSON response dictionaries are generated from validated domain models.
        session = current(request)
        with session.lock:
            return [
                row.model_dump(mode="json")
                for row in list_pending(session.business.business_id, session.settings)
            ]

    @app.get("/api/audit")
    def audit_data(request: Request) -> list[dict[str, Any]]:
        session = current(request)
        with session.lock:
            return [
                row.model_dump(mode="json")
                for row in audit.list_history(session.business.business_id, session.settings)
            ]

    @app.get("/api/diary")
    def diary_data(request: Request) -> dict[str, Any] | None:
        session = current(request)
        with session.lock:
            view = surface.diary(session)
            return view.model_dump(mode="json") if view else None

    @app.get("/exports/{kind}")
    def download(request: Request, kind: Literal["csv", "html"]) -> Response:
        session = current(request)
        with session.lock:
            content = surface.export(session, kind, DEMO_LABEL if demo else AWS_LABEL)
        return Response(
            content,
            media_type="text/csv" if kind == "csv" else "text/html",
            headers={"Content-Disposition": f'attachment; filename="evidence.{kind}"'},
        )

    return app
