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
  if (text == null) return "";
  const div = document.createElement("div");
  div.textContent = String(text);
  return div.innerHTML;
}

const DEMO_BUSINESS = ALLERGUARD_DEMO_DATA.business;
const REPLAY_ALERTS = ALLERGUARD_DEMO_DATA.alerts;

const DRAFT_PREFIX = "DRAFT ONLY — NOT SENT — AWAITING OWNER APPROVAL:";
function londonDate(value = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/London", year: "numeric", month: "2-digit", day: "2-digit"
  }).format(value);
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
const navLinks = document.querySelectorAll("nav a[data-nav]");
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
    else recordDecision(id, button.dataset.action);
  });
  startFreshBtn.addEventListener("click", startFresh);
  runReplayBtn.addEventListener("click", runReplay);
  fileDiaryBtn.addEventListener("click", fileDiary);
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
  if (state.sessionActive && state.demoRun) {
    summary.hidden = false;
    const pending = state.alerts.filter(a => a.decision === "ESCALATE" && !a.ownerDecision);
    const silent = state.alerts.filter(a => a.decision === "SILENT").length;

    statPending.textContent = pending.length;
    statAssessed.textContent = state.alerts.length;
    statSilent.textContent = silent;
    statEvents.textContent = state.auditLog.length;

    cycleStatus.hidden = false;
    cycleStatus.textContent = `Last replay: ${state.lastCycle.status} · ${state.lastCycle.status === "EMPTY" ? "0 retrieved; evidence unchanged" : "5 retrieved · 2 silent · 3 escalated"}. ${state.lastCycle.timestamp}`;

    awsEvidence.hidden = false;
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
      <h2>${escapeHtml(alert.reason)}</h2>
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
        <button class="primary-btn" data-action="approve" data-alert="${escapeHtml(alert.id)}">Approve draft</button>
        <button class="secondary" data-action="edit" data-alert="${escapeHtml(alert.id)}">Edit draft</button>
        <button class="secondary" data-action="decline" data-alert="${escapeHtml(alert.id)}">Decline</button>
      </div>
      <div id="edit-${escapeHtml(alert.id)}" class="edit-form" hidden>
        <h3>Edit action pack</h3>
        <label for="pack-${escapeHtml(alert.id)}">Edited JSON (modify values below)</label>
        <textarea id="pack-${escapeHtml(alert.id)}" rows="12">${escapeHtml(JSON.stringify(alert.action_pack, null, 2))}</textarea>
        <button data-action="save-edit" data-alert="${escapeHtml(alert.id)}">Record edited draft</button>
        <p class="form-error" id="error-${escapeHtml(alert.id)}"></p>
      </div>
    </article>
  `).join("");
}

// Toggle edit form
function toggleEdit(alertId) {
  const form = document.getElementById(`edit-${alertId}`);
  form.hidden = !form.hidden;
}

// Submit edit
function submitEdit(alertId) {
  const textarea = document.getElementById(`pack-${alertId}`);
  const errorEl = document.getElementById(`error-${alertId}`);

  try {
    const pack = JSON.parse(textarea.value);
    validatePack(pack);
    recordDecision(alertId, "edit", pack);
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

  auditContent.innerHTML = state.auditLog.map(row => `
    <article class="card ${row.event === "match_decision" && row.decision === "SILENT" ? "silent-row" : ""}">
      <div class="card-top">
        <span class="chip">${escapeHtml(row.event.replace(/_/g, " "))}</span>
        <time>${escapeHtml(new Date(row.timestamp).toLocaleString("en-GB"))}</time>
      </div>
      <h2>${escapeHtml(row.alert_title || (row.entry_date ? "Daily diary · " + row.entry_date : "Event"))}</h2>
      ${row.reason ? `<p>${escapeHtml(row.reason)}</p>` : ""}
      ${row.tier ? `<p>Tier: ${escapeHtml(row.tier)} · Gate: ${escapeHtml(row.decision)}</p>` : ""}
      ${row.owner_decision ? `<p><b>Owner choice: ${escapeHtml(row.owner_decision.decision.toUpperCase())}</b></p>` : ""}
      ${row.notification ? `<p>Notification: ${escapeHtml(row.notification.outcome)} · ${escapeHtml(row.notification.provider)} · ${escapeHtml(row.notification.mode)}. Provider acceptance does not prove inbox receipt.</p>` : ""}
      <details>
        <summary>Inspect stored evidence</summary>
        <pre>${escapeHtml(JSON.stringify(row, null, 2))}</pre>
      </details>
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
      state: a.ownerDecision.decision.toUpperCase()
    }));

  diaryContent.innerHTML = `
    <article class="card">
      <h2>Original filing</h2>
      <p>${escapeHtml(state.diary.summary)}</p>
      <p>Opening: <b>unconfirmed</b> · Closing: <b>unconfirmed</b> at original filing.</p>
      <p class="muted">Evidence cutoff: ${escapeHtml(new Date(state.diary.evidence_cutoff).toLocaleString("en-GB"))}</p>

      ${state.diaryConfirmation ? `
        <h2>Stored owner confirmation</h2>
        <p>Opening: ${escapeHtml(state.diaryConfirmation.opening_status)} · Closing: ${escapeHtml(state.diaryConfirmation.closing_status)}</p>
        <p>${escapeHtml(state.diaryConfirmation.note)}</p>
        <p class="muted">Mode: ${escapeHtml(state.diaryConfirmation.mode)}. Stored first answers retained.</p>
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

    <section>
      <h2>Recall decisions as of this view</h2>
      <p>Later decisions appear here without rewriting the original filing. Choices do not prove stock or customer actions.</p>
      ${linkedRecalls.length > 0 ? linkedRecalls.map(link => `
        <article class="card">
          <span class="chip">${escapeHtml(link.state)}</span>
          <h3>${escapeHtml(link.alert_title)}</h3>
          <p class="muted">${escapeHtml(link.alert_id)}</p>
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
  const columns = ["mode", "timestamp", "event", "alert_id", "owner_choice", "payload_json"];
  const cell = value => {
    let text = String(value ?? "");
    if (/^[=+@\-\t\r]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  };
  return [columns, ...state.auditLog.map(row => [
    "PUBLIC BROWSER SIMULATION - NOT PRODUCTION DATA", row.timestamp,
    row.event, row.alert_id || "", row.owner_decision?.decision || "", JSON.stringify(row)
  ])].map(row => row.map(cell).join(",")).join("\r\n");
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

// Export HTML
function exportHtml() {
  if (state.auditLog.length === 0) return;

  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AllerGuard Demo Evidence</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
.warning { background: #C15E12; color: white; padding: 1rem; margin-bottom: 2rem; border-radius: 6px; }
h1 { font-size: 2rem; margin-bottom: 1rem; }
.event { background: #fff; border: 1px solid #E3E9EC; padding: 1.5rem; margin-bottom: 1rem; border-radius: 6px; }
.meta { color: #55666E; font-size: 0.875rem; margin-bottom: 0.5rem; }
pre { background: #F7F9FA; padding: 1rem; border-radius: 6px; overflow-x: auto; }
</style>
</head>
<body>
<div class="warning">
<strong>PUBLIC BROWSER SIMULATION</strong>
<p>This evidence was generated by a browser-only demonstration. It is not production data. No AWS, Bedrock, DynamoDB, SES, SNS, customer communications, or stock actions were executed.</p>
</div>

<h1>AllerGuard Demo Evidence</h1>
<p>Generated: ${escapeHtml(new Date().toLocaleString("en-GB"))}</p>
<p>Session: ${escapeHtml(state.business.name)}</p>

${state.auditLog.map(row => `
<div class="event">
<div class="meta">${escapeHtml(new Date(row.timestamp).toLocaleString("en-GB"))} · ${escapeHtml(row.event.replace(/_/g, " "))}</div>
<h2>${escapeHtml(row.alert_title || (row.entry_date ? "Daily diary · " + row.entry_date : "Event"))}</h2>
${row.reason ? `<p>${escapeHtml(row.reason)}</p>` : ""}
${row.tier ? `<p>Tier: ${escapeHtml(row.tier)} · Gate: ${escapeHtml(row.decision)}</p>` : ""}
${row.owner_decision ? `<p><strong>Owner choice: ${escapeHtml(row.owner_decision.decision.toUpperCase())}</strong></p>` : ""}
<details>
<summary>Full record</summary>
<pre>${escapeHtml(JSON.stringify(row, null, 2))}</pre>
</details>
</div>
`).join("")}

<footer style="margin-top: 3rem; padding-top: 2rem; border-top: 1px solid #E3E9EC; color: #55666E;">
<p>AllerGuard · Public demonstration · ${escapeHtml(new Date().getFullYear().toString())}</p>
</footer>
</body>
</html>`;

  const blob = new Blob([html], { type: "text/html" });
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
