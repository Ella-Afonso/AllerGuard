"""Local read-only HTML evidence report, rendered from persisted audit entries."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from src.domain.diary import DiaryEvent, DiaryRecord, DiaryView, RecallDiaryLink
from src.domain.models import AuditEntry, AuditEvent, GateDecision, NotificationMode
from src.domain.presentation import (
    assessment_result_label,
    assessment_source_label,
    event_display_label,
    format_display_date,
    format_display_time,
    gate_result_label,
    owner_outcome_label,
)

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
    if entry.event is AuditEvent.NOTIFICATION_SENT:
        if entry.notification is not None and entry.notification.mode is NotificationMode.SIMULATED:
            return "Notification recorded · simulated, no message sent"
        return "Notification recorded · inbox receipt unverified"
    if entry.event is AuditEvent.DECISION_RECORDED and entry.owner_decision is not None:
        outcome = owner_outcome_label(entry.owner_decision.decision)
        return f"{event_display_label(entry.event)} · {outcome}"
    return event_display_label(entry.event)


def _recall_link_card(
    link: RecallDiaryLink, *, additional: set[str], anchors: dict[str, str]
) -> str:
    filed = link.event_id in additional
    origin = "linked after filing" if filed else "filed with the original diary"
    pending = link.state == "pending"
    status = "Awaiting owner review" if pending else "Decision record filed"
    choice = owner_outcome_label(link.state)
    tone = "silent" if pending else "escalate"
    anchor = anchors.get(link.event_id, "")
    view = (
        f'<p><a href="#{escape(anchor, quote=True)}">View decision evidence</a></p>'
        if anchor
        else ""
    )
    return (
        f'<article class="event {tone}">'
        f'<span class="badge">{escape(status)}</span>'
        f"<h3>{escape(link.alert_title)}</h3>"
        "<dl>"
        f"<dt>Recall title</dt><dd>{escape(link.alert_title)}</dd>"
        f"<dt>Owner choice</dt><dd>{escape(choice)}</dd>"
        f"<dt>Recorded time</dt><dd>{escape(format_display_time(link.evidence_at))}</dd>"
        f"<dt>Status</dt><dd>{escape(status)}</dd>"
        "</dl>"
        f'<p class="caption">{escape(origin)}.</p>{view}'
        "</article>"
    )


def _diary_section(
    views: list[DiaryView],
    records: list[DiaryRecord],
    *,
    anchors: dict[str, str],
) -> str:
    if not records:
        return ""
    parts = ['<section class="events" aria-label="Daily diary"><h2>Daily diary</h2>']
    counts = {event: sum(row.event is event for row in records) for event in DiaryEvent}
    parts.append(
        f'<p class="caption">Diary filings: {counts[DiaryEvent.FILED]} · '
        f"Owner confirmations: {counts[DiaryEvent.CONFIRMED]} · "
        f"Diary errors: {counts[DiaryEvent.ERROR]}. "
        "These events are separate from the recall counts above.</p>"
    )
    for view in views:
        diary = view.filed.diary
        if diary is None:
            continue
        parts.append(
            '<article class="event">'
            f'<span class="badge">Daily record · '
            f"{escape(format_display_date(diary.entry_date))}</span>"
            "<h2>Today's food-safety record</h2>"
            "<p>Recall decisions linked automatically from stored evidence.</p>"
            "<p>Original filing: opening unconfirmed; closing unconfirmed.</p>"
            f'<p class="caption">Filed {escape(format_display_time(diary.filed_at))}. '
            f"Evidence cutoff {escape(format_display_time(diary.evidence_cutoff))}. "
            "Business timezone Europe/London.</p>"
        )
        if diary.summary_source.value == "model":
            parts.append(
                '<p class="caption">Optional model wording, unverified narrative; '
                "the structured evidence below is authoritative.</p>"
            )
        parts.append(f"<p>{escape(diary.summary)}</p>")
        if view.confirmation is not None and view.confirmation.confirmation is not None:
            answers = view.confirmation.confirmation
            parts.append(
                f"<p><b>Owner confirmation</b>: opening "
                f"{escape(answers.opening_status.value)}; closing "
                f"{escape(answers.closing_status.value)}.</p>"
                f"<p>Note: {escape(answers.note or 'None')}</p>"
                f'<p class="caption">Recorded '
                f"{escape(format_display_time(view.confirmation.timestamp))}</p>"
            )
        else:
            parts.append("<p><b>Awaiting owner confirmation</b>: opening and closing.</p>")
        parts.append(f"<p>{escape('; '.join(diary.exceptions))}</p>")
        additional = {link.event_id for link in view.additional_links}
        parts.append(
            f"<h3>Linked recall decisions as of "
            f"{escape(format_display_time(view.as_of))}</h3>"
            '<div class="link-grid">'
        )
        for link in view.current_recall_actions:
            parts.append(_recall_link_card(link, additional=additional, anchors=anchors))
        parts.append(
            '</div><p class="caption">Choices record approval, editing or decline. '
            "They do not prove customer or stock actions were executed. "
            "No customer notice or stock action was executed. "
            "Detailed append-only evidence is retained by the application.</p></article>"
        )
    parts.append("</section>")
    return "".join(parts)


def write_audit_report(
    entries: list[AuditEntry],
    output: Path,
    *,
    storage_label: str,
    diary_views: list[DiaryView] | None = None,
    diary_records: list[DiaryRecord] | None = None,
) -> Path:
    """Export a snapshot, with no action buttons and no claims of notification.

    Callers must pass rows read back from the audit store via the audit tool.
    This function does not read DynamoDB, call the matcher, or mutate stored data.
    """
    summary = summarize_audit_entries(entries)
    anchors: dict[str, str] = {}
    decision_n = 0
    for entry in entries:
        if entry.event is AuditEvent.DECISION_RECORDED:
            decision_n += 1
            anchors[entry.entry_id] = f"decision-{decision_n}"
    cards: list[str] = []
    decision_n = 0
    for index, entry in enumerate(entries, 1):
        is_error = entry.event is AuditEvent.MATCH_ERROR
        if is_error:
            state = "error"
        elif entry.decision is GateDecision.ESCALATE:
            state = "escalate"
        else:
            state = "silent"
        candidates = ", ".join(entry.candidate_ids) or "No recorded candidates"
        inventory = ", ".join(entry.matched_items) or "No recorded inventory link"
        extra = ""
        if entry.event is AuditEvent.ESCALATION_QUEUED:
            extra += (
                "<p>Queue status: queued for owner review. "
                "Recording a choice does not execute stock or customer actions.</p>"
            )
        if entry.notification is not None:
            receipt = entry.notification
            extra += (
                f"<p>Simulated notification outcome: {escape(receipt.outcome.value)} · "
                f"{escape(receipt.provider.value)} · {escape(receipt.mode.value)}. "
                "Provider acceptance does not prove inbox receipt.</p>"
            )
        packs = ""
        if entry.owner_decision is not None:
            record = entry.owner_decision
            original = record.original_action_pack
            extra += (
                f"<p><b>Owner choice: {escape(owner_outcome_label(record.decision))}</b> "
                f"at {escape(format_display_time(record.decided_at))}. "
                "This records an owner choice. It does not execute stock or customer actions.</p>"
            )
            packs = (
                "<h3>Original draft</h3><dl>"
                f"<dt>Stock-pull draft</dt><dd>{escape(original.pull)}</dd>"
                f"<dt>Staff note</dt><dd>{escape(original.staff_note)}</dd>"
                f"<dt>Customer notice — draft only</dt>"
                f"<dd>{escape(original.customer_notice)}</dd>"
                f"<dt>Substitution</dt><dd>{escape(original.substitution)}</dd></dl>"
            )
            if record.edited_pack is not None:
                edited = record.edited_pack
                packs += (
                    "<h3>Edited draft</h3><dl>"
                    f"<dt>Stock-pull draft</dt><dd>{escape(edited.pull)}</dd>"
                    f"<dt>Staff note</dt><dd>{escape(edited.staff_note)}</dd>"
                    f"<dt>Customer notice — draft only</dt>"
                    f"<dd>{escape(edited.customer_notice)}</dd>"
                    f"<dt>Substitution</dt><dd>{escape(edited.substitution)}</dd></dl>"
                )
        identity = ""
        if entry.event is AuditEvent.DECISION_RECORDED:
            decision_n += 1
            identity = f' id="decision-{decision_n}"'
        cards.append(f"""
        <article class="event {state}"{identity}>
          <div class="event-top"><span class="number">{index:02d}</span>
            <span class="badge">{escape(_event_label(entry))}</span>
            <time>{escape(format_display_time(entry.timestamp))}</time></div>
          <h2>{escape(entry.alert_title)}</h2>
          <p class="reason">{escape(entry.reason)}</p>
          <dl>
            <dt>Alert reference</dt><dd>{escape(entry.alert_id)}</dd>
            <dt>Assessment result</dt><dd>{escape(assessment_result_label(entry.tier))}</dd>
            <dt>Gate result</dt><dd>{escape(gate_result_label(entry.decision))}</dd>
            <dt>Assessment source</dt>
            <dd>{escape(assessment_source_label(entry.mode, entry.draft_source))}</dd>
            <dt>Business</dt><dd>{escape(entry.business_id)}</dd>
            <dt>Matching candidates</dt><dd>{escape(candidates)}</dd>
            <dt>Matched inventory</dt><dd>{escape(inventory)}</dd>
          </dl>
          <div class="source">{_source(entry.source_url)}</div>
          {extra}{packs}
          <p class="caption">This event is retained in the append-only audit trail.</p>
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
:root{--color-bg:#f4f1ea;--color-surface:#fffcf7;--color-ink:#1b2430;
--color-ink-soft:#5c6573;--color-line:#d9d2c6;--color-primary:#2f4cb0;
--color-primary-ink:#243a8a;--color-primary-soft:#e8edf8;--color-silent:#5d6a7a;
--color-possible:#b56a12;color-scheme:light;
font-family:"Segoe UI",system-ui,-apple-system,sans-serif;color:var(--color-ink);
background:var(--color-bg)}
*{box-sizing:border-box}body{margin:0;background:var(--color-bg);color:var(--color-ink)}
main{max-width:1100px;margin:0 auto;padding:48px 28px 70px}
.brand{letter-spacing:.12em;font-size:13px;font-weight:800;color:var(--color-primary-ink);
text-transform:uppercase}
header{margin:35px 0 28px;display:grid;grid-template-columns:1fr 270px;gap:30px;align-items:end}
h1{font-family:Palatino,"Palatino Linotype",Georgia,serif;font-size:clamp(32px,5vw,52px);
letter-spacing:-.04em;line-height:1.08;margin:12px 0 20px}
h3{font-family:Palatino,Georgia,serif;font-size:1.05rem;margin:20px 0 8px}
.intro{font-size:17px;line-height:1.6;max-width:650px;color:var(--color-ink-soft)}
.scope{border-left:3px solid var(--color-primary);padding:3px 0 3px 20px;line-height:1.6;
font-size:13px;color:var(--color-ink-soft)}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:30px 0}
.stat{padding:23px;background:var(--color-surface);border:1px solid var(--color-line);
border-radius:12px;box-shadow:0 1px 2px rgba(27,36,48,.06)}
.stat b{font-size:37px;display:block;letter-spacing:-.04em;color:var(--color-ink)}
.stat span{font-size:13px;color:var(--color-ink-soft)}
.caption{font-size:13px;color:var(--color-ink-soft);line-height:1.6}
.events,.link-grid{display:grid;gap:18px;margin-top:20px}
.event{background:var(--color-surface);border:1px solid var(--color-line);
border-left:5px solid var(--color-silent);border-radius:12px;padding:25px 28px}
.event.escalate{border-left-color:var(--color-possible)}
.event.error{border-left-color:#8b3a4a}
.event-top{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.number{font-size:12px;color:var(--color-ink-soft)}
.badge{font-size:12px;font-weight:700;background:var(--color-primary-soft);
color:var(--color-primary-ink);padding:7px 11px;border-radius:20px}
.escalate .badge{background:#f6ead7;color:#7a480c}
.error .badge{background:#f3dde2;color:#8b3a4a}
time{margin-left:auto;color:var(--color-ink-soft);font-size:12px}
h2{font-size:21px;line-height:1.35;margin:20px 0 12px}
.reason{font-size:16px;line-height:1.7;max-width:900px}
.source{margin-top:20px;font-size:13px}a{color:var(--color-primary-ink);text-underline-offset:4px}
dl{display:grid;grid-template-columns:11rem 1fr;gap:10px 12px;margin:16px 0}
dt{color:var(--color-ink-soft);font-weight:600}dd{margin:0;overflow-wrap:anywhere}
footer{margin-top:32px;font-size:12px;line-height:1.7;color:var(--color-ink-soft);
border-top:1px solid var(--color-line);padding-top:20px}
.storage{font-size:12px;background:var(--color-primary-soft);color:var(--color-primary-ink);
padding:9px 13px;display:inline-block;border-radius:6px}
@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}}
@media(max-width:650px){main{padding:26px 18px}header{grid-template-columns:1fr}
.event{padding:20px}time{margin-left:0}dl{grid-template-columns:1fr}}
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
        (summary.audit_events, "Recall audit events" if diary_records else "Stored audit events"),
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
    document += "These are historical event counts, not current inbox totals. "
    document += "Detailed append-only evidence is retained by the application. "
    document += (
        "This download is not tamper-proof storage and is not a legal or "
        "compliance certificate.</p>"
    )
    document += _diary_section(diary_views or [], diary_records or [], anchors=anchors)
    document += '<section class="events">' + "".join(cards) + "</section>"
    document += f"""<footer>Generated from stored evidence supplied by the caller after
    reading the audit store. This report is evidence presentation only — not a second
    safety gate, not tamper-proof storage, and not a legal or compliance certificate.
    Detailed append-only evidence is retained by the application. {footer_notice}</footer>
    </main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return output.resolve()
