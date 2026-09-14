"use strict";

// Browser-only state - no persistence, no network
let state = {
  sessionActive: false,
  demoRun: false,
  alerts: [],
  auditLog: [],
  diary: null,
  diaryConfirmation: null,
  business: null
};

// Escape HTML to prevent XSS
function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

const DEMO_BUSINESS = ALLERGUARD_DEMO_DATA.business;
const REPLAY_ALERTS = ALLERGUARD_DEMO_DATA.alerts;

const DRAFT_PREFIX = "DRAFT ONLY — NOT SENT — AWAITING OWNER APPROVAL:";
function londonDate(value = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/London", year: "numeric", month: "2-digit", day: "2-digit"
  }).format(value);
}
const EVENT_LABELS = {
  match_decision: "Assessment recorded",
  match_error: "Assessment failed",
  escalation_queued: "Escalation queued",
  notification_sent: "Notification recorded",
  notification_failed: "Notification failed",
  notification_unknown: "Notification outcome unknown",
  decision_recorded: "Owner decision recorded",
  diary_filed: "Daily diary filed",
  diary_confirmed: "Diary confirmation recorded",
  diary_error: "Diary error recorded"
};
function eventDisplayLabel(event) {
  return EVENT_LABELS[event] || String(event || "").replace(/_/g, " ");
}
function formatDisplayTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZoneName: "short"
  }).formatToParts(date).map(part => [part.type, part.value]));
  const month = parts.month === "Sept" ? "Sep" : parts.month;
  return `${Number(parts.day)} ${month} ${parts.year}, ${parts.hour}:${parts.minute} ${parts.timeZoneName}`;
}
function formatDisplayDate(value) {
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [year, month, day] = value.split("-").map(Number);
    const utcNoon = new Date(Date.UTC(year, month - 1, day, 12));
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/London", day: "numeric", month: "short", year: "numeric"
    }).formatToParts(utcNoon).map(part => [part.type, part.value]));
    const monthName = parts.month === "Sept" ? "Sep" : parts.month;
    return `${Number(parts.day)} ${monthName} ${parts.year}`;
  }
  const stamp = formatDisplayTime(value);
  return stamp.split(",")[0] || stamp;
}
function alertTitleFor(alertId) {
  const match = state.alerts.find(item => item.id === alertId);
  return match ? match.title : alertId;
}
function shortEvidenceReference(entryId) {
  const identity = String(entryId || "").split("#")[0];
  if (identity.length < 16) return identity;
  return `${identity.slice(0, 8)}…${identity.slice(-5)}`;
}
function assessmentResultLabel(tier) {
  return ({
    NO_MATCH: "No recorded match",
    POSSIBLE: "Possible match",
    LIKELY: "Likely match",
    CONFIRMED: "Confirmed match"
  })[tier] || "";
}
function gateResultLabel(decision) {
  if (decision === "SILENT") return "Handled quietly";
  if (decision === "ESCALATE") return "Owner review required";
  return "";
}
function ownerChoiceLabel(choice) {
  return ({approve: "Approve", edit: "Edit", decline: "Decline"})[choice] || choice;
}
function factRows(rows) {
  return `<dl class="facts">${rows.map(([label, value]) =>
    `<dt>${escapeHtml(label)}</dt><dd>${value}</dd>`).join("")}</dl>`;
}
function packFields(pack) {
  if (!pack) return "";
  return factRows([
    ["Stock-pull draft", escapeHtml(pack.pull)],
    ["Staff note", escapeHtml(pack.staff_note)],
    ["Customer notice — draft only", escapeHtml(pack.customer_notice)],
    ["Substitution", escapeHtml(pack.substitution)]
  ]);
}
function evidenceMarkup(row, index) {
  let body = "";
  if (row.event === "diary_filed") {
    const links = row.linked_decisions || [];
    body = `<h3>Daily diary filing</h3>${factRows([
      ["Diary date", escapeHtml(formatDisplayDate(row.entry_date || ""))],
      ["Filed at", escapeHtml(formatDisplayTime(row.timestamp))],
      ["Evidence cutoff", escapeHtml(formatDisplayTime(row.evidence_cutoff || row.timestamp))],
      ["Opening", "unconfirmed"],
      ["Closing", "unconfirmed"],
      ["Summary source", "Injected replay proposal"]
    ])}<p>${escapeHtml(row.summary || "")}</p><h3>Linked recall decisions</h3>${
      links.length
        ? `<ul>${links.map(link => `<li>${escapeHtml(alertTitleFor(link.alert_id))} — ${escapeHtml(ownerChoiceLabel(link.decision))}</li>`).join("")}</ul>`
        : "<p>No linked recall evidence yet.</p>"
    }`;
  } else if (row.event === "diary_confirmed") {
    const confirmation = row.confirmation || {};
    body = `<h3>Diary confirmation</h3>${factRows([
      ["Recorded at", escapeHtml(formatDisplayTime(row.timestamp))],
      ["Opening result", escapeHtml(confirmation.opening_status || "")],
      ["Closing result", escapeHtml(confirmation.closing_status || "")],
      ["Note", escapeHtml(confirmation.note || "None")],
      ["Confirmation mode", escapeHtml(confirmation.mode || "")]
    ])}<p>First answers retained.</p>`;
  } else if (row.event === "decision_recorded" && row.owner_decision) {
    const original = row.owner_decision.original_pack || {};
    const edited = row.owner_decision.pack;
    body = `<h3>Owner decision</h3>${factRows([
      ["Decision", escapeHtml(ownerChoiceLabel(row.owner_decision.decision))],
      ["Recorded at", escapeHtml(formatDisplayTime(row.timestamp))],
      ["Recall title", escapeHtml(row.alert_title || "")],
      ["Alert reference", escapeHtml(row.alert_id || "")]
    ])}<h3>Original draft</h3>${packFields(original)}${
      row.owner_decision.decision === "edit" ? `<h3>Edited draft</h3>${packFields(edited)}` : ""
    }<p>This records an owner choice. It does not execute stock or customer actions.</p>`;
  } else {
    body = `<h3>Assessment</h3>${factRows([
      ["Alert reference", escapeHtml(row.alert_id || "")],
      ["Assessment recorded", escapeHtml(formatDisplayTime(row.timestamp))],
      ["Assessment result", escapeHtml(assessmentResultLabel(row.tier))],
      ["Gate result", escapeHtml(gateResultLabel(row.decision))],
      ["Explanation", escapeHtml(row.reason || "")],
      ["Policy", "matcher-gate-v1"],
      ["Assessment source", "Injected replay proposal"]
    ])}<h3>Recorded business context</h3>${factRows([
      ["Business", "demo-cafe"],
      ["Matching candidates", "No recorded candidates"],
      ["Matched inventory", "No recorded inventory link"],
      ["Source alert", "See the FSA source on the inbox card"]
    ])}`;
    if (row.event === "escalation_queued") {
      body += `<h3>Notification / decision</h3>${factRows([["Queue status", "Queued for owner review"]])}
        <p>Recording a choice does not execute stock or customer actions.</p>`;
    }
    if (row.notification) {
      body += `<h3>Notification / decision</h3>${factRows([[
        "Simulated notification outcome",
        escapeHtml(`${row.notification.outcome} · ${row.notification.provider} · ${row.notification.mode}`)
      ]])}<p>Provider acceptance does not prove inbox receipt. Recording a choice does not execute stock or customer actions.</p>`;
    }
  }
  return `<details class="inspect"><summary>Inspect stored evidence</summary>
    <div class="evidence">${body}</div>
    <p class="muted">This event is retained in the append-only audit trail.</p>
  </details>`;
}
function packFromForm(alertId) {
  return {
    pull: document.getElementById(`pull-${alertId}`).value,
    staff_note: document.getElementById(`staff-${alertId}`).value,
    customer_notice: document.getElementById(`notice-${alertId}`).value,
    substitution: document.getElementById(`sub-${alertId}`).value
  };
}
function validatePack(pack) {
  const fields = ["pull", "staff_note", "customer_notice", "substitution"];
  if (!pack || typeof pack !== "object" || Array.isArray(pack) ||
      Object.keys(pack).length !== fields.length ||
      fields.some(key => typeof pack[key] !== "string" || !pack[key].trim() || pack[key].length > 4000)) {
    throw new Error("Provide exactly four nonempty text fields: " + fields.join(", "));
  }
  if (!pack.customer_notice.startsWith(DRAFT_PREFIX)) {
    throw new Error("Customer notice must retain the draft-only prefix.");
  }
  if (pack.substitution !== "No substitution suggested.") {
    throw new Error("Substitution selection is unavailable in this public simulation.");
  }
  return pack;
}

// DOM elements
const feedback = document.getElementById("feedback");
const startFreshBtn = document.getElementById("start-fresh");
const runReplayBtn = document.getElementById("run-replay");
const summary = document.getElementById("summary");
const cycleStatus = document.getElementById("cycle-status");
const awsEvidence = document.getElementById("aws-evidence");

// Stats elements
const statPending = document.getElementById("stat-pending");
const statAssessed = document.getElementById("stat-assessed");
const statSilent = document.getElementById("stat-silent");
const statEvents = document.getElementById("stat-events");

// View elements
const views = {
  inbox: document.getElementById("view-inbox"),
  audit: document.getElementById("view-audit"),
  diary: document.getElementById("view-diary"),
  business: document.getElementById("view-business")
};

// Content elements
const inboxContent = document.getElementById("inbox-content");
const auditContent = document.getElementById("audit-content");
const diaryContent = document.getElementById("diary-content");
const businessContent = document.getElementById("business-content");
const diaryDate = document.getElementById("diary-date");

// Buttons
const fileDiaryBtn = document.getElementById("file-diary");
const exportCsvBtn = document.getElementById("export-csv");
const exportHtmlBtn = document.getElementById("export-html");

// Navigation
const navLinks = document.querySelectorAll("[data-nav]");
let currentView = "inbox";

// Initialize
function init() {
  inboxContent.addEventListener("click", event => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    event.preventDefault();
    const id = button.dataset.alert;
    if (button.dataset.action === "audit") switchView("audit");
    else if (button.dataset.action === "edit") toggleEdit(id);
    else if (button.dataset.action === "save-edit") submitEdit(id);
    else if (button.dataset.action === "cancel-edit") cancelEdit(id);
    else recordDecision(id, button.dataset.action);
  });
  startFreshBtn.addEventListener("click", startFresh);
  runReplayBtn.addEventListener("click", runReplay);
  fileDiaryBtn.addEventListener("click", fileDiary);
  diaryContent.addEventListener("click", event => {
    const link = event.target.closest("[data-nav]");
    if (!link) return;
    event.preventDefault();
    switchView(link.dataset.nav);
  });
  exportCsvBtn.addEventListener("click", exportCsv);
  exportHtmlBtn.addEventListener("click", exportHtml);

  navLinks.forEach(link => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      switchView(link.dataset.nav);
    });
  });

  // Set diary date
  diaryDate.textContent = new Date().toLocaleDateString("en-GB", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "Europe/London"
  });
}

// Show feedback
function showFeedback(message, type = "info") {
  feedback.textContent = message;
  feedback.className = type;
  setTimeout(() => {
    feedback.textContent = "";
    feedback.className = "";
  }, 5000);
}

// Start fresh demo
function startFresh() {
  state = {
    sessionActive: true,
    demoRun: false,
    alerts: [],
    auditLog: [],
    diary: null,
    diaryConfirmation: null,
    business: DEMO_BUSINESS
  };

  runReplayBtn.disabled = false;
  fileDiaryBtn.disabled = false;
  exportCsvBtn.disabled = true;
  exportHtmlBtn.disabled = true;

  showFeedback("Demo session started. Run replay demo to assess five historical alerts.", "success");
  updateUI();
}

// Run replay demo
function runReplay() {
  if (!state.sessionActive) return;
  if (state.demoRun) {
    state.lastCycle = { status: "EMPTY", timestamp: new Date().toISOString() };
    showFeedback("No new alerts. Stored decisions and evidence are unchanged.", "success");
    updateUI();
    return;
  }

  showFeedback("Processing 5 historical FSA alerts...", "info");

  // Add alerts to state
  state.alerts = REPLAY_ALERTS.map(alert => ({
    ...alert,
    ownerDecision: null,
    notificationSent: alert.decision === "ESCALATE"
  }));

  // Create audit entries
  const timestamp = new Date().toISOString();

  state.alerts.forEach(alert => {
    // Match decision audit
    state.auditLog.push({
      timestamp,
      event: "match_decision",
      alert_id: alert.id,
      alert_title: alert.title,
      tier: alert.tier,
      decision: alert.decision,
      reason: alert.reason
    });

    // Escalation queued for non-silent
    if (alert.decision === "ESCALATE") {
      state.auditLog.push({
        timestamp,
        event: "escalation_queued",
        alert_id: alert.id,
        alert_title: alert.title,
        tier: alert.tier,
        decision: alert.decision
      });

      // Simulated notification
      state.auditLog.push({
        timestamp,
        event: "notification_sent",
        alert_id: alert.id,
        alert_title: alert.title,
        notification: {
          outcome: "ACCEPTED",
          provider: "SIMULATED",
          mode: "simulated"
        }
      });
    }
  });

  state.demoRun = true;
  state.lastCycle = { status: "COMMITTED", timestamp };
  exportCsvBtn.disabled = false;
  exportHtmlBtn.disabled = false;

  showFeedback("Replay complete: 5 alerts assessed, 2 handled quietly, 3 escalated for owner review.", "success");
  updateUI();
  switchView("inbox");
}

// Record owner decision
function recordDecision(alertId, choice, editedPack = null) {
  const alert = state.alerts.find(a => a.id === alertId);
  if (!alert || alert.decision !== "ESCALATE" || alert.ownerDecision || !["approve", "edit", "decline"].includes(choice)) return;

  const timestamp = new Date().toISOString();
  const pack = structuredClone(validatePack(editedPack || alert.action_pack));

  alert.ownerDecision = {
    decision: choice,
    timestamp,
    pack
  };

  state.auditLog.push({
    timestamp,
    event: "decision_recorded",
    alert_id: alertId,
    alert_title: alert.title,
    owner_decision: {
      decision: choice,
      original_pack: structuredClone(alert.action_pack),
      pack
    }
  });

  showFeedback(`Decision recorded: ${choice.toUpperCase()}. Recorded in this public browser simulation. No stock or customer action was executed.`, "success");
  updateUI();
}

// File diary
function fileDiary() {
  if (!state.sessionActive || state.diary) return;

  const timestamp = new Date().toISOString();

  state.diary = {
    timestamp,
    entry_date: londonDate(),
    summary: "Daily safety record prepared. Opening and closing status await explicit owner confirmation.",
    evidence_cutoff: timestamp,
    linked_decisions: state.alerts.filter(a => a.ownerDecision && londonDate(new Date(a.ownerDecision.timestamp)) === londonDate()).map(a => ({alert_id: a.id, decision: a.ownerDecision.decision}))
  };

  state.auditLog.push({
    timestamp,
    event: "diary_filed",
    entry_date: state.diary.entry_date,
    summary: state.diary.summary,
    evidence_cutoff: state.diary.evidence_cutoff,
    linked_decisions: structuredClone(state.diary.linked_decisions)
  });

  showFeedback("Diary filed for today. Confirm opening and closing status below.", "success");
  updateUI();
  switchView("diary");
}

// Confirm diary
function confirmDiary(opening, closing, note) {
  if (!state.diary || state.diaryConfirmation) {
    showFeedback("Diary already confirmed. First-write-wins: later amendment is not implemented.", "error");
    return;
  }

  if (!["confirmed", "exception"].includes(opening) || !["confirmed", "exception"].includes(closing)) {
    showFeedback("Choose both opening and closing answers.", "error");
    return;
  }
  if ((opening === "exception" || closing === "exception") && !note.trim()) {
    showFeedback("Exception note is required when either answer is Exception.", "error");
    return;
  }

  const timestamp = new Date().toISOString();

  state.diaryConfirmation = {
    timestamp,
    opening_status: opening,
    closing_status: closing,
    note: note || "Standard operation confirmed",
    mode: "simulated"
  };

  state.auditLog.push({
    timestamp,
    event: "diary_confirmed",
    entry_date: state.diary.entry_date,
    confirmation: state.diaryConfirmation
  });

  showFeedback("Diary confirmation recorded. First answers retained.", "success");
  updateUI();
}

// Update UI
function updateUI() {
  exportCsvBtn.disabled = exportHtmlBtn.disabled = state.auditLog.length === 0;
  // Update stats
  if (state.sessionActive) {
    summary.hidden = false;
    const pending = state.alerts.filter(a => a.decision === "ESCALATE" && !a.ownerDecision);
    const silent = state.alerts.filter(a => a.decision === "SILENT").length;
    statPending.textContent = pending.length;
    statAssessed.textContent = state.alerts.length;
    statSilent.textContent = silent;
    statEvents.textContent = state.auditLog.length;
    if (state.demoRun && state.lastCycle) {
      cycleStatus.hidden = false;
      cycleStatus.textContent = `Last replay: ${state.lastCycle.status} · ${state.lastCycle.status === "EMPTY" ? "0 retrieved; evidence unchanged" : "5 retrieved · 2 silent · 3 escalated"}. ${formatDisplayTime(state.lastCycle.timestamp)}`;
      awsEvidence.hidden = false;
    } else {
      cycleStatus.hidden = true;
      awsEvidence.hidden = true;
    }
  } else {
    statPending.textContent = statAssessed.textContent = statSilent.textContent = statEvents.textContent = "0";
    summary.hidden = true;
    cycleStatus.hidden = true;
    awsEvidence.hidden = true;
  }

  // Update inbox
  renderInbox();

  // Update audit
  renderAudit();

  // Update diary
  renderDiary();

  // Update business
  renderBusiness();
}

// Render inbox
function renderInbox() {
  if (!state.sessionActive || !state.demoRun) {
    inboxContent.innerHTML = `
      <div class="empty">
        <h2>Nothing needs your review right now.</h2>
        <p>Run the replay demo to assess five historical alerts.</p>
        <p>Start a demo above to create your own isolated café session.</p>
      </div>
    `;
    return;
  }

  const pending = state.alerts.filter(a => a.decision === "ESCALATE" && !a.ownerDecision);

  if (pending.length === 0) {
    inboxContent.innerHTML = `
      <div class="empty">
        <h2>All decisions recorded.</h2>
        <p>Silent decisions remain visible in the audit trail.</p>
        <a href="#audit" data-action="audit">See the audit trail →</a>
      </div>
    `;
    return;
  }

  inboxContent.innerHTML = pending.map(alert => `
    <article class="card tier-${escapeHtml(alert.tier)}">
      <div class="card-top">
        <span class="chip ${escapeHtml(alert.tier)}">${escapeHtml(alert.tier)}</span>
        <span>Awaiting your decision</span>
      </div>
      <h2 class="reason">${escapeHtml(alert.reason)}</h2>
      <p>${escapeHtml(alert.title)}</p>
      <a href="${escapeHtml(alert.alert_url)}" target="_blank" rel="noopener noreferrer">Read the FSA source ↗</a>
      <p class="muted">Injected demonstration draft · Simulated matcher</p>
      <dl>
        <dt>Stock-pull draft</dt><dd>${escapeHtml(alert.action_pack.pull)}</dd>
        <dt>Customer Notice</dt><dd>${escapeHtml(alert.action_pack.customer_notice)}</dd>
        <dt>Staff note</dt><dd>${escapeHtml(alert.action_pack.staff_note)}</dd>
        <dt>Substitution</dt><dd>${escapeHtml(alert.action_pack.substitution)}</dd>
      </dl>
      <div class="decision-buttons">
        <button data-action="approve" data-alert="${escapeHtml(alert.id)}">Approve draft</button>
        <button class="secondary" data-action="edit" data-alert="${escapeHtml(alert.id)}">Edit draft</button>
        <button class="choice-decline" data-action="decline" data-alert="${escapeHtml(alert.id)}">Decline</button>
      </div>
      <div id="edit-${escapeHtml(alert.id)}" class="edit-form" hidden>
        <h3>Review and edit draft</h3>
        <p>Change the proposed wording if needed. Your edits are recorded as a decision; they do not send notices or execute stock actions.</p>
        <label for="pull-${escapeHtml(alert.id)}">Stock-pull draft</label>
        <textarea id="pull-${escapeHtml(alert.id)}" name="pull" rows="4">${escapeHtml(alert.action_pack.pull)}</textarea>
        <label for="staff-${escapeHtml(alert.id)}">Staff note</label>
        <textarea id="staff-${escapeHtml(alert.id)}" name="staff_note" rows="4">${escapeHtml(alert.action_pack.staff_note)}</textarea>
        <label for="notice-${escapeHtml(alert.id)}">Customer notice — draft only</label>
        <p class="field-help">This remains a draft. It will not be sent.</p>
        <textarea id="notice-${escapeHtml(alert.id)}" name="customer_notice" rows="4">${escapeHtml(alert.action_pack.customer_notice)}</textarea>
        <label for="sub-${escapeHtml(alert.id)}">Substitution</label>
        <p class="field-help">Substitution selection is not available in this public simulation.</p>
        <textarea id="sub-${escapeHtml(alert.id)}" name="substitution" rows="2" readonly>${escapeHtml(alert.action_pack.substitution)}</textarea>
        <div class="toolbar">
          <button type="button" data-action="save-edit" data-alert="${escapeHtml(alert.id)}">Record edited draft</button>
          <button type="button" class="secondary" data-action="cancel-edit" data-alert="${escapeHtml(alert.id)}">Cancel</button>
        </div>
        <p class="form-error" id="error-${escapeHtml(alert.id)}"></p>
      </div>
    </article>
  `).join("");
}

// Toggle edit form
function toggleEdit(alertId) {
  const form = document.getElementById(`edit-${alertId}`);
  form.hidden = !form.hidden;
  if (!form.hidden) document.getElementById(`pull-${alertId}`).focus();
}
function cancelEdit(alertId) {
  const form = document.getElementById(`edit-${alertId}`);
  const alert = state.alerts.find(item => item.id === alertId);
  if (alert) {
    document.getElementById(`pull-${alertId}`).value = alert.action_pack.pull;
    document.getElementById(`staff-${alertId}`).value = alert.action_pack.staff_note;
    document.getElementById(`notice-${alertId}`).value = alert.action_pack.customer_notice;
    document.getElementById(`sub-${alertId}`).value = alert.action_pack.substitution;
  }
  const errorEl = document.getElementById(`error-${alertId}`);
  if (errorEl) errorEl.textContent = "";
  form.hidden = true;
}
function submitEdit(alertId) {
  const errorEl = document.getElementById(`error-${alertId}`);
  try {
    recordDecision(alertId, "edit", packFromForm(alertId));
  } catch (e) {
    errorEl.textContent = "Invalid draft: " + e.message;
  }
}

// Render audit
function renderAudit() {
  if (state.auditLog.length === 0) {
    auditContent.innerHTML = `
      <div class="empty">
        <h2>No evidence recorded in this session.</h2>
        <p>Run the replay from the Inbox.</p>
      </div>
    `;
    return;
  }

  auditContent.innerHTML = state.auditLog.map((row, index) => `
    <article class="card ${row.event === "match_decision" && row.decision === "SILENT" ? "silent-row" : ""}">
      <div class="card-top">
        <span class="chip">${escapeHtml(eventDisplayLabel(row.event))}</span>
        <time>${escapeHtml(formatDisplayTime(row.timestamp))}</time>
      </div>
      <h2>${escapeHtml(row.alert_title || (row.entry_date ? "Daily diary · " + formatDisplayDate(row.entry_date) : "Event"))}</h2>
      ${row.reason ? `<p>${escapeHtml(row.reason)}</p>` : ""}
      ${row.tier ? `<p>${escapeHtml(assessmentResultLabel(row.tier))} · ${escapeHtml(gateResultLabel(row.decision))}</p>` : ""}
      ${row.owner_decision ? `<p><b>Owner choice: ${escapeHtml(ownerChoiceLabel(row.owner_decision.decision))}</b></p>` : ""}
      ${row.notification ? `<p>Notification: ${escapeHtml(row.notification.outcome)} · ${escapeHtml(row.notification.provider)} · ${escapeHtml(row.notification.mode)}. Provider acceptance does not prove inbox receipt.</p>` : ""}
      ${evidenceMarkup(row, index)}
    </article>
  `).join("");
}

// Render diary
function renderDiary() {
  if (!state.diary) {
    diaryContent.innerHTML = `
      <div class="empty">
        <h2>No diary filed for today.</h2>
        <button id="file-diary-btn" ${!state.sessionActive ? "disabled" : ""}>Prepare today's diary</button>
        <p>Preparing the record does not confirm opening or closing tasks. First-write-wins: later amendment is not implemented in this public simulation.</p>
      </div>
    `;
    const btn = document.getElementById("file-diary-btn");
    if (btn) btn.addEventListener("click", fileDiary);
    return;
  }

  const linkedRecalls = state.alerts
    .filter(a => a.ownerDecision && londonDate(new Date(a.ownerDecision.timestamp)) === state.diary.entry_date)
    .map(a => ({
      alert_id: a.id,
      alert_title: a.title,
      state: a.ownerDecision.decision.toUpperCase(),
      timestamp: a.ownerDecision.timestamp
    }));

  diaryContent.innerHTML = `
    <div class="timeline">
    <article class="card">
      <h2>Original filing</h2>
      <p>${escapeHtml(state.diary.summary)}</p>
      <p>Opening: <b>unconfirmed</b> · Closing: <b>unconfirmed</b> at original filing.</p>
      <p class="muted">Filed ${escapeHtml(formatDisplayTime(state.diary.timestamp))}. Evidence cutoff ${escapeHtml(formatDisplayTime(state.diary.evidence_cutoff))}.</p>
    </article>
    <article class="card">
      ${state.diaryConfirmation ? `
        <h2>Stored owner confirmation</h2>
        <p>Opening: ${escapeHtml(state.diaryConfirmation.opening_status)} · Closing: ${escapeHtml(state.diaryConfirmation.closing_status)}</p>
        <p>${escapeHtml(state.diaryConfirmation.note)}</p>
        <p class="muted">Recorded ${escapeHtml(formatDisplayTime(state.diaryConfirmation.timestamp))}. Mode: ${escapeHtml(state.diaryConfirmation.mode)}. Stored first answers retained.</p>
      ` : `
        <h2>Your explicit answers</h2>
        <p>Opening and closing await explicit owner confirmation.</p>
        <form id="diary-confirm-form">
          <label for="opening">Opening</label>
          <select id="opening" name="opening_status" required>
            <option value="" selected disabled>Choose an answer</option>
            <option value="confirmed">Confirmed</option>
            <option value="exception">Exception</option>
          </select>

          <label for="closing">Closing</label>
          <select id="closing" name="closing_status" required>
            <option value="" selected disabled>Choose an answer</option>
            <option value="confirmed">Confirmed</option>
            <option value="exception">Exception</option>
          </select>

          <label for="note">Exception note (required if either answer is Exception)</label>
          <textarea id="note" name="note" maxlength="2000" rows="3"></textarea>

          <button type="submit">Record my answers</button>
          <p class="form-error" id="diary-form-error"></p>
        </form>
      `}
    </article>
    </div>

    <section class="timeline">
      <h2>Recall decisions as of this view</h2>
      <p>Later decisions appear here without rewriting the original filing. Choices do not prove stock or customer actions.</p>
      ${linkedRecalls.length > 0 ? linkedRecalls.map(link => `
        <article class="card">
          <span class="chip ${escapeHtml(link.state.toLowerCase())}">${escapeHtml(link.state)}</span>
          <h3>${escapeHtml(link.alert_title)}</h3>
          <p>Recorded ${escapeHtml(formatDisplayTime(link.timestamp))}</p>
          <p>Owner choice: ${escapeHtml(ownerChoiceLabel(link.state.toLowerCase()))}</p>
          <p><a href="#audit" data-nav="audit">View audit trail</a></p>
        </article>
      `).join("") : "<p>No linked recall evidence yet.</p>"}
    </section>
  `;

  if (!state.diaryConfirmation) {
    const form = document.getElementById("diary-confirm-form");
    if (form) {
      form.addEventListener("submit", (e) => {
        e.preventDefault();
        const opening = form.elements.opening_status.value;
        const closing = form.elements.closing_status.value;
        const note = form.elements.note.value;
        confirmDiary(opening, closing, note);
      });
    }
  }
}

// Render business
function renderBusiness() {
  if (!state.business) {
    businessContent.innerHTML = "<p>Start a demo to load the fictional café.</p>";
    return;
  }

  businessContent.innerHTML = `
    <div class="inventory-grid">
    <h2>${escapeHtml(state.business.name)}</h2>
    <p>Handled allergens: ${escapeHtml(state.business.handled_allergens.join(", "))}</p>

    ${state.business.inventory.map(item => `
      <article class="card">
        <h2>${escapeHtml(item.name)}</h2>
        <p>${escapeHtml(item.kind)}${item.brand ? " · " + escapeHtml(item.brand) : ""}</p>
        <dl>
          <dt>Ingredients</dt><dd>${escapeHtml(item.ingredients.join(", ") || "None recorded")}</dd>
          <dt>Allergens</dt><dd>${escapeHtml(item.allergens.join(", ") || "None recorded")}</dd>
          <dt>Supplier</dt><dd>${escapeHtml(item.supplier || "None recorded")}</dd>
          <dt>Batch codes</dt><dd>${escapeHtml(item.batch_codes.join(", ") || "Unknown")}</dd>
        </dl>
      </article>
    `).join("")}
    </div>
  `;
}

// Switch view
function switchView(viewName) {
  currentView = viewName;

  // Update nav
  navLinks.forEach(link => {
    if (link.dataset.nav === viewName) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });

  // Update views
  Object.keys(views).forEach(key => {
    if (key === viewName) {
      views[key].classList.add("active");
    } else {
      views[key].classList.remove("active");
    }
  });
}

// One rectangular row per event, retaining the complete evidence payload.
function buildCsv() {
  const columns = [
    "mode", "display_time", "event_label", "alert_reference", "alert_title",
    "tier", "gate_result", "owner_choice", "reason", "pull", "staff_note",
    "customer_notice", "diary_date", "notes"
  ];
  const cell = value => {
    let text = String(value ?? "");
    if (/^[=+@\-\t\r]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  };
  return [columns, ...state.auditLog.map(row => {
    const pack = row.owner_decision?.pack || {};
    const confirmation = row.confirmation || {};
    return [
      "PUBLIC BROWSER SIMULATION - NOT PRODUCTION DATA",
      formatDisplayTime(row.timestamp),
      eventDisplayLabel(row.event),
      row.alert_id || "",
      row.alert_title || "",
      assessmentResultLabel(row.tier),
      gateResultLabel(row.decision),
      ownerChoiceLabel(row.owner_decision?.decision || ""),
      row.reason || "",
      pack.pull || "",
      pack.staff_note || "",
      pack.customer_notice || "",
      row.entry_date ? formatDisplayDate(row.entry_date) : "",
      confirmation.note || ""
    ];
  })].map(row => row.map(cell).join(",")).join("\r\n");
}

// Export CSV
function exportCsv() {
  if (state.auditLog.length === 0) return;

  const csv = buildCsv();
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `allerguard-demo-${Date.now()}.csv`;
  a.click();
  URL.revokeObjectURL(url);

  showFeedback("CSV downloaded. File contains PUBLIC BROWSER SIMULATION label.", "success");
}

function reportEventClass(row) {
  if (row.event === "match_error" || row.event === "diary_error") return "error";
  if (row.decision === "ESCALATE" || row.event === "escalation_queued" || row.event === "decision_recorded") {
    return "escalate";
  }
  return "silent";
}
function reportEventBody(row) {
  if (row.event === "diary_filed") {
    const links = row.linked_decisions || [];
    return `<h3>Daily diary filing</h3>${factRows([
      ["Diary date", escapeHtml(formatDisplayDate(row.entry_date || ""))],
      ["Recorded time", escapeHtml(formatDisplayTime(row.timestamp))],
      ["Evidence cutoff", escapeHtml(formatDisplayTime(row.evidence_cutoff || row.timestamp))],
      ["Opening", "unconfirmed"],
      ["Closing", "unconfirmed"],
      ["Draft status", "Prepared; awaiting owner confirmation"]
    ])}<p>${escapeHtml(row.summary || "")}</p><h3>Linked recall decisions</h3>${
      links.length
        ? `<ul>${links.map(link => `<li>${escapeHtml(alertTitleFor(link.alert_id))} — ${escapeHtml(ownerChoiceLabel(link.decision))}</li>`).join("")}</ul>`
        : "<p>No linked recall evidence yet.</p>"
    }`;
  }
  if (row.event === "diary_confirmed") {
    const confirmation = row.confirmation || {};
    return `<h3>Diary confirmation</h3>${factRows([
      ["Recorded time", escapeHtml(formatDisplayTime(row.timestamp))],
      ["Opening result", escapeHtml(confirmation.opening_status || "")],
      ["Closing result", escapeHtml(confirmation.closing_status || "")],
      ["Note", escapeHtml(confirmation.note || "None")],
      ["Confirmation mode", escapeHtml(confirmation.mode || "")]
    ])}`;
  }
  if (row.event === "decision_recorded" && row.owner_decision) {
    const original = row.owner_decision.original_pack || {};
    const edited = row.owner_decision.pack;
    return `<h3>Owner decision</h3>${factRows([
      ["Owner choice", escapeHtml(ownerChoiceLabel(row.owner_decision.decision))],
      ["Recorded time", escapeHtml(formatDisplayTime(row.timestamp))],
      ["Alert reference", escapeHtml(row.alert_id || "")],
      ["Recall title", escapeHtml(row.alert_title || "")]
    ])}<h3>Original draft</h3>${packFields(original)}${
      row.owner_decision.decision === "edit" ? `<h3>Edited draft</h3>${packFields(edited)}` : ""
    }<p>This records an owner choice. It does not execute stock or customer actions.</p>`;
  }
  let body = `<h3>Assessment</h3>${factRows([
    ["Alert reference", escapeHtml(row.alert_id || "")],
    ["Recorded time", escapeHtml(formatDisplayTime(row.timestamp))],
    ["Assessment result", escapeHtml(assessmentResultLabel(row.tier))],
    ["Gate result", escapeHtml(gateResultLabel(row.decision))],
    ["Explanation", escapeHtml(row.reason || "")],
    ["Recorded business", "demo-cafe"],
    ["Matched inventory", "No recorded inventory link"],
    ["Draft status", row.event === "escalation_queued" ? "Queued for owner review" : "Recorded"]
  ])}`;
  if (row.notification) {
    body += `<h3>Notification</h3>${factRows([[
      "Simulated notification outcome",
      escapeHtml(`${row.notification.outcome} · ${row.notification.provider} · ${row.notification.mode}`)
    ]])}<p>Provider acceptance does not prove inbox receipt. No customer communication or stock action was executed.</p>`;
  }
  return body;
}
function buildHtml() {
  const generated = formatDisplayTime(new Date());
  const cafe = escapeHtml(state.business?.name || "Fictional café");
  const silent = state.alerts.filter(a => a.decision === "SILENT").length;
  const escalated = state.alerts.filter(a => a.decision === "ESCALATE").length;
  const decisions = state.alerts.filter(a => a.ownerDecision).length;
  const diaryBlock = state.diary ? `
    <section class="events" aria-label="Daily diary">
      <h2>Daily diary</h2>
      <article class="event">
        <div class="event-top"><span class="badge">Daily record · ${escapeHtml(formatDisplayDate(state.diary.entry_date))}</span>
        <time>${escapeHtml(formatDisplayTime(state.diary.timestamp))}</time></div>
        <p>${escapeHtml(state.diary.summary)}</p>
        <p>Opening and closing remain unconfirmed in the original filing.
        ${state.diaryConfirmation
          ? `Later owner confirmation: opening ${escapeHtml(state.diaryConfirmation.opening_status)}; closing ${escapeHtml(state.diaryConfirmation.closing_status)}.`
          : "Owner confirmation has not been recorded."}</p>
        <p class="caption">Choices record approval, editing or decline. They do not prove customer or stock actions were executed. Detailed append-only evidence is retained by this public browser simulation.</p>
      </article>
    </section>` : "";
  const cards = state.auditLog.map((row, index) => `
    <article class="event ${reportEventClass(row)}">
      <div class="event-top"><span class="number">${String(index + 1).padStart(2, "0")}</span>
        <span class="badge">${escapeHtml(eventDisplayLabel(row.event))}</span>
        <time>${escapeHtml(formatDisplayTime(row.timestamp))}</time></div>
      <h2>${escapeHtml(row.alert_title || (row.entry_date ? "Daily diary · " + formatDisplayDate(row.entry_date) : "Event"))}</h2>
      ${row.reason ? `<p class="reason">${escapeHtml(row.reason)}</p>` : ""}
      ${reportEventBody(row)}
      <p class="caption">This event is retained in the append-only audit trail of this public browser simulation.</p>
    </article>`).join("");
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AllerGuard · Demo evidence</title>
<style>
:root{color-scheme:light;font-family:"Segoe UI",system-ui,sans-serif;color:#1b2430;background:#f4f1ea}
*{box-sizing:border-box}body{margin:0}main{max-width:1100px;margin:0 auto;padding:48px 28px 70px}
.brand{letter-spacing:.12em;font-size:13px;font-weight:800;color:#243a8a;text-transform:uppercase}
.banner{background:#243a8a;color:#fff;padding:16px 20px;border-radius:12px;margin:20px 0}
.banner strong{display:block;letter-spacing:.08em;font-size:12px;margin-bottom:8px}
.banner p{margin:0;font-size:14px;color:#e8edf8}
header{margin:28px 0;display:grid;grid-template-columns:1fr 270px;gap:30px;align-items:end}
h1{font-family:Palatino,Georgia,serif;font-size:clamp(32px,5vw,52px);letter-spacing:-.04em;line-height:1.08;margin:12px 0 20px}
.intro{font-size:17px;line-height:1.6;max-width:650px;color:#5c6573}
.scope{border-left:3px solid #2f4cb0;padding:3px 0 3px 20px;line-height:1.6;font-size:13px;color:#5c6573}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:30px 0}
.stat{padding:23px;background:#fffcf7;border:1px solid #d9d2c6;border-radius:12px}
.stat b{font-size:37px;display:block;letter-spacing:-.04em}.stat span{font-size:13px;color:#5c6573}
.caption{font-size:13px;color:#5c6573;line-height:1.6}.events{display:grid;gap:18px;margin-top:20px}
.event{background:#fffcf7;border:1px solid #d9d2c6;border-left:5px solid #5d6a7a;border-radius:12px;padding:25px 28px}
.event.escalate{border-left-color:#b56a12}.event.error{border-left-color:#8b3a4a}
.event-top{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.number{font-size:12px;color:#5c6573}
.badge{font-size:12px;font-weight:700;background:#e8edf8;color:#243a8a;padding:7px 11px;border-radius:20px}
.escalate .badge{background:#f6ead7;color:#7a480c}.error .badge{background:#f3dde2;color:#8b3a4a}
time{margin-left:auto;color:#5c6573;font-size:12px}h2{font-size:21px;line-height:1.35;margin:20px 0 12px}
h3{font-family:Palatino,Georgia,serif;font-size:1.05rem;margin:20px 0 8px}
.reason{font-size:16px;line-height:1.7}a{color:#243a8a}
dl{display:grid;grid-template-columns:11rem 1fr;gap:10px}dt{color:#5c6573;font-weight:600}dd{margin:0;overflow-wrap:anywhere}
footer{margin-top:32px;font-size:12px;line-height:1.7;color:#5c6573;border-top:1px solid #d9d2c6;padding-top:20px}
@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}}
@media(max-width:650px){main{padding:26px 18px}header{grid-template-columns:1fr}dl{grid-template-columns:1fr}time{margin-left:0}}
</style></head><body><main>
<div class="banner"><strong>PUBLIC BROWSER SIMULATION</strong>
<p>Interactive replay demo · synthetic business · simulated notifications. No customer communication or stock action was executed. This page does not call AWS, Bedrock, DynamoDB, SES or SNS.</p></div>
<div class="brand">AllerGuard / Decision evidence</div>
<header><div>
<h1>Quiet when it can be.<br>Clear when it matters.</h1>
<p class="intro">A read-only copy of this browser session: silent assessments, owner reviews, drafts and diary records. Generated ${escapeHtml(generated)} for ${cafe}.</p>
</div>
<div class="scope">Synthetic/public recall data.<br>Fictional café inventory.<br>
Browser-only simulation.<br>No customer or stock action was executed.</div></header>
<section class="stats">
<div class="stat"><b>${state.auditLog.length}</b><span>Stored evidence</span></div>
<div class="stat"><b>${state.alerts.length}</b><span>Distinct assessments</span></div>
<div class="stat"><b>${silent}</b><span>Silent outcomes</span></div>
<div class="stat"><b>${escalated}</b><span>Owner review required</span></div>
<div class="stat"><b>${decisions}</b><span>Owner choices recorded</span></div>
</section>
<p class="caption">Events are historical records from this public simulation, not current pending totals. Repeated titles show separate linked events. Detailed append-only evidence is retained by this browser session. This download is not tamper-proof storage and is not a legal or compliance certificate.</p>
${diaryBlock}
<section class="events">${cards}</section>
<footer>AllerGuard · Public demonstration · Decisions record a choice. They do not execute stock actions or send customer notices.</footer>
</main></body></html>`;
}

function exportHtml() {
  if (state.auditLog.length === 0) return;

  const blob = new Blob([buildHtml()], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `allerguard-demo-${Date.now()}.html`;
  a.click();
  URL.revokeObjectURL(url);

  showFeedback("HTML evidence downloaded. File contains PUBLIC BROWSER SIMULATION label.", "success");
}

// Initialize on load
init();
