"""Local read-only HTML evidence report, rendered from persisted audit entries."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from src.domain.models import AuditEntry, AuditEvent, GateDecision, NotificationMode

# Official FSA hostnames only — hostname equality after urlsplit, not substring checks.
FSA_LINK_HOSTS = frozenset({"alerts.food.gov.uk", "data.food.gov.uk"})


@dataclass(frozen=True)
class AuditReportSummary:
    """Counts derived only from persisted rows supplied by the caller."""

    audit_events: int
    distinct_assessments: int
    silent_decision_events: int
    escalation_decision_events: int
    error_events: int


def summarize_audit_entries(entries: list[AuditEntry]) -> AuditReportSummary:
    """Derive report counts from stored audit events, not from local processing counters."""
    return AuditReportSummary(
        audit_events=len(entries),
        distinct_assessments=len({entry.assessment_id for entry in entries}),
        silent_decision_events=sum(
            entry.event is AuditEvent.MATCH_DECISION and entry.decision is GateDecision.SILENT
            for entry in entries
        ),
        escalation_decision_events=sum(
            entry.event is AuditEvent.MATCH_DECISION and entry.decision is GateDecision.ESCALATE
            for entry in entries
        ),
        error_events=sum(entry.event is AuditEvent.MATCH_ERROR for entry in entries),
    )


def _source(url: str) -> str:
    """Only official HTTPS FSA sources become links; all other input stays escaped text."""
    parsed = urlsplit(url)
    if parsed.scheme == "https" and parsed.hostname in FSA_LINK_HOSTS:
        return f'<a href="{escape(url, quote=True)}" rel="noreferrer">Open FSA source ↗</a>'
    return escape(url)


def _event_label(entry: AuditEntry) -> str:
    if entry.event is AuditEvent.MATCH_ERROR:
        return "Assessment failed · requires review"
    if entry.event is AuditEvent.ESCALATION_QUEUED:
        return "Action pack queued for owner review"
    if entry.event is AuditEvent.NOTIFICATION_SENT:
        if entry.notification is not None and entry.notification.mode is NotificationMode.SIMULATED:
            return "Simulated notification accepted · no message sent"
        return "Owner notification accepted · inbox receipt unverified"
    if entry.event is AuditEvent.NOTIFICATION_FAILED:
        return "Owner notification attempt failed"
    if entry.event is AuditEvent.NOTIFICATION_UNKNOWN:
        return "Owner notification outcome unknown"
    if entry.event is AuditEvent.DECISION_RECORDED and entry.owner_decision is not None:
        return f"Owner choice recorded · {entry.owner_decision.decision.value}"
    if entry.decision is GateDecision.SILENT:
        return "Recorded quietly"
    return "Requires review"


def _gate_label(entry: AuditEntry) -> str:
    if entry.event is AuditEvent.MATCH_ERROR:
        return "Requires review (assessment incomplete)"
    if entry.decision is GateDecision.SILENT:
        return "Silent"
    return "Requires review"


def write_audit_report(entries: list[AuditEntry], output: Path, *, storage_label: str) -> Path:
    """Export a snapshot, with no action buttons and no claims of notification.

    Callers must pass rows read back from the audit store via the audit tool.
    This function does not read DynamoDB, call the matcher, or mutate stored data.
    """
    summary = summarize_audit_entries(entries)
    cards: list[str] = []
    for index, entry in enumerate(entries, 1):
        is_error = entry.event is AuditEvent.MATCH_ERROR
        state = "error" if is_error else entry.decision.value
        tier = entry.tier.value if entry.tier is not None else "Unassessed"
        floor = entry.floor_tier.value if entry.floor_tier is not None else "Unassessed"
        candidates = ", ".join(entry.candidate_ids) or "None"
        draft_fact = ""
        if entry.event is AuditEvent.ESCALATION_QUEUED and entry.draft_source is not None:
            draft_fact = f"<span>Draft source <b>{escape(entry.draft_source.value)}</b></span>"
        notification_fact = ""
        if entry.notification is not None:
            receipt = entry.notification
            provider = escape(receipt.provider.value)
            outcome = escape(receipt.outcome.value)
            mode = escape(receipt.mode.value)
            notification_fact = (
                f"<span>Notification <b>{outcome}</b> via <b>{provider}</b> "
                f"({mode}; provider acceptance is not inbox receipt)</span>"
            )
        decision_fact = ""
        decision_detail = ""
        if entry.owner_decision is not None:
            record = entry.owner_decision
            decision_fact = f"<span>Owner choice <b>{escape(record.decision.value)}</b></span>"
            original = record.original_action_pack
            decision_detail = (
                f"<dt>Owner choice</dt><dd>{escape(record.decision.value)} at "
                f"{escape(record.decided_at.isoformat())}</dd>"
                f"<dt>Original pull</dt><dd>{escape(original.pull)}</dd>"
                f"<dt>Original staff note</dt><dd>{escape(original.staff_note)}</dd>"
                f"<dt>Original customer notice</dt><dd>{escape(original.customer_notice)}</dd>"
                f"<dt>Original substitution</dt><dd>{escape(original.substitution)}</dd>"
            )
            if record.edited_pack is not None:
                edited = record.edited_pack
                decision_detail += (
                    f"<dt>Edited pull</dt><dd>{escape(edited.pull)}</dd>"
                    f"<dt>Edited staff note</dt><dd>{escape(edited.staff_note)}</dd>"
                    f"<dt>Edited customer notice</dt><dd>{escape(edited.customer_notice)}</dd>"
                    f"<dt>Edited substitution</dt><dd>{escape(edited.substitution)}</dd>"
                )
        cards.append(f"""
        <article class="event {state}">
          <div class="event-top"><span class="number">{index:02d}</span>
            <span class="badge">{escape(_event_label(entry))}</span>
            <time>{escape(entry.timestamp.isoformat())}</time></div>
          <h2>{escape(entry.alert_title)}</h2>
          <p class="reason">{escape(entry.reason)}</p>
          <div class="facts"><span>Event <b>{escape(entry.event.value)}</b></span>
            <span>Floor <b>{escape(floor)}</b></span>
            <span>Final <b>{escape(tier)}</b></span>
            <span>Gate <b>{escape(_gate_label(entry))}</b></span>
            <span>Mode <b>{escape(entry.mode.value)}</b></span>
            {draft_fact}</div>
            <div class="facts">{notification_fact}{decision_fact}</div>
          <div class="source">{_source(entry.source_url)}</div>
          <details><summary>Inspect recorded evidence</summary>
            <dl><dt>Business</dt><dd>{escape(entry.business_id)}</dd>
            <dt>Assessment</dt><dd>{escape(entry.assessment_id)}</dd>
            <dt>Alert version</dt><dd>{escape(entry.alert_id)} ·
            {escape(entry.alert_modified.isoformat())}</dd>
            <dt>Matched stock</dt><dd>{escape(", ".join(entry.matched_items) or "None")}</dd>
            <dt>Candidate IDs</dt><dd>{escape(candidates)}</dd>
            <dt>Policy / model</dt><dd>{escape(entry.policy_version)} /
            {escape(entry.model_id)}</dd>
            <dt>Event ID</dt><dd>{escape(entry.entry_id)}</dd>
            <dt>Error type</dt><dd>{escape(entry.error_type or "None")}</dd></dl>
            <dl>{decision_detail}</dl>
          </details>
        </article>""")
    has_owner_events = any(
        entry.event
        in {
            AuditEvent.NOTIFICATION_SENT,
            AuditEvent.NOTIFICATION_FAILED,
            AuditEvent.NOTIFICATION_UNKNOWN,
            AuditEvent.DECISION_RECORDED,
        }
        for entry in entries
    )
    scope_notice = (
        "Owner notification evidence and owner choices are shown below.<br>"
        "No customer or stock action was executed."
        if has_owner_events
        else "No owner notification or choice is recorded in this snapshot."
    )
    footer_notice = (
        "Notification evidence is provider acceptance/failure/uncertainty, not inbox receipt. "
        "No customer, stock or action-pack execution was performed."
        if has_owner_events
        else "No notification, approval, or stock action was performed."
    )
    document = (
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>AllerGuard · Decision evidence</title>
<style>
:root{color-scheme:light;font-family:Inter,Segoe UI,Arial,sans-serif;
color:#183c34;background:#f3f5ee}
*{box-sizing:border-box}body{margin:0}main{max-width:1100px;margin:0 auto;padding:48px 28px 70px}
.brand{letter-spacing:.18em;font-size:13px;font-weight:800;color:#45655b}
header{margin:35px 0 28px;display:grid;grid-template-columns:1fr 270px;gap:30px;align-items:end}
h1{font-size:clamp(32px,5vw,58px);letter-spacing:-.055em;line-height:1.03;margin:12px 0 20px}
.intro{font-size:17px;line-height:1.6;max-width:650px;color:#47655b}
.scope{border-left:3px solid #b2c1ad;padding:3px 0 3px 20px;line-height:1.6;font-size:13px}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:30px 0}
.stat{padding:23px;background:white;border:1px solid #dce4d6;border-radius:14px}
.stat b{font-size:37px;display:block;letter-spacing:-.04em}.stat span{font-size:13px;color:#547066}
.caption{font-size:13px;color:#557367;line-height:1.6}.events{display:grid;gap:18px;margin-top:20px}
.event{background:#fff;border:1px solid #dce4d6;border-left:5px solid #709b86;border-radius:14px;
padding:25px 28px}.event.escalate{border-left-color:#c98626}.event.error{border-left-color:#bd5a43}
.event-top{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.number{font-size:12px;color:#769386}
.badge{font-size:12px;font-weight:700;background:#eaf3eb;padding:7px 11px;border-radius:20px}
.escalate .badge{background:#fff0d8;color:#805219}.error .badge{background:#fdebe5;color:#8f402d}
time{margin-left:auto;color:#678173;font-size:12px}
h2{font-size:21px;line-height:1.35;margin:20px 0 12px}
.reason{font-size:16px;line-height:1.7;max-width:900px}.facts{display:flex;gap:22px;flex-wrap:wrap;
font-size:12px;color:#587366;margin-top:18px}.facts b{color:#183c34;margin-left:5px}
.source{margin-top:20px;font-size:13px}a{color:#216e59;text-underline-offset:4px}
details{margin-top:22px;border-top:1px solid #edf0e8;padding-top:15px;font-size:12px}
summary{cursor:pointer;color:#486456}dl{display:grid;grid-template-columns:140px 1fr;gap:10px}
dt{color:#668072}dd{margin:0;overflow-wrap:anywhere}footer{margin-top:32px;font-size:12px;
line-height:1.7;color:#5b7669} .storage{font-size:12px;background:#e5ebe0;padding:9px 13px;
display:inline-block;border-radius:6px}
@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}}
@media(max-width:650px){main{padding:26px 18px}header{grid-template-columns:1fr}.event{padding:20px}
time{margin-left:0}dl{grid-template-columns:1fr}}
</style></head><body><main><div class="brand">ALLERGUARD / DECISION EVIDENCE</div>
<header><div><h1>Quiet when it can be.<br>Clear when it matters.</h1>
<p class="intro">A read-only view of stored audit events: completed match decisions,
decisions that require review, and assessments that could not be completed.</p></div>
<div class="scope">Historical FSA alerts.<br>Fictional business inventory.<br>
Matching → code gate → drafted/fallback action pack → pending queue → audit.<br>
"""
        + scope_notice
        + """</div></header>
"""
    )
    document += f'<div class="storage">{escape(storage_label)}</div><section class="stats">'
    for count, label in [
        (summary.audit_events, "Stored audit events"),
        (summary.distinct_assessments, "Distinct assessments"),
        (summary.silent_decision_events, "Silent decision events"),
        (summary.escalation_decision_events, "Requires-review decision events"),
        (summary.error_events, "Assessment error events"),
    ]:
        document += f'<div class="stat"><b>{count}</b><span>{escape(label)}</span></div>'
    document += '</section><p class="caption">Audit events are append-only store rows, '
    document += "not alerts processed and not notifications sent. One assessment may "
    document += "produce separate match, queue, notification and owner-choice events, "
    document += "or error and recovery events. Repeated titles show this linked history. "
    document += '"Requires review" means the gate recorded ESCALATE; it does not mean '
    document += "the owner was notified or that a decision is still pending. "
    document += "These are historical event counts, not current inbox totals.</p>"
    document += '<section class="events">' + "".join(cards) + "</section>"
    document += f"""<footer>Generated from AuditEntry records supplied by the caller after
    reading the audit store. This report is evidence presentation only — not a second
    safety gate, not tamper-proof storage, and not proof of delivery. {footer_notice}</footer>
    </main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return output.resolve()
