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

// Fictional demo-cafe business
const DEMO_BUSINESS = {
  id: "demo-cafe",
  name: "The Walnut & Whisk Café",
  handled_allergens: ["milk", "gluten", "eggs", "nuts"],
  inventory: [
    {
      name: "Doritos Chilli Heatwave",
      kind: "snack",
      brand: "PepsiCo",
      ingredients: ["corn", "vegetable oils", "chilli seasoning"],
      allergens: [],
      supplier: "PepsiCo UK",
      batch_codes: []
    },
    {
      name: "Walnut Brownie",
      kind: "dessert",
      brand: null,
      ingredients: ["flour", "sugar", "butter", "eggs", "walnuts", "cocoa"],
      allergens: ["gluten", "eggs", "milk", "nuts"],
      supplier: "Daily Bakes Ltd",
      batch_codes: []
    },
    {
      name: "Oat Milk",
      kind: "ingredient",
      brand: "Oatly",
      ingredients: ["oats", "water", "salt"],
      allergens: [],
      supplier: "Oatly UK",
      batch_codes: []
    },
    {
      name: "Sourdough Bread",
      kind: "ingredient",
      brand: null,
      ingredients: ["wheat flour", "water", "salt", "sourdough culture"],
      allergens: ["gluten"],
      supplier: "Local Bakery Co",
      batch_codes: []
    }
  ]
};

// Five historical FSA alerts with realistic data
const REPLAY_ALERTS = [
  {
    id: "FSA-PRIN-43-2026",
    title: "Organic black olives recall due to undeclared sulphites",
    tier: "NO_MATCH",
    decision: "SILENT",
    reason: "Not stocked; no sulphite handling",
    alert_url: "https://www.food.gov.uk/news-alerts/alert/fsa-prin-43-2026"
  },
  {
    id: "FSA-PRIN-39-2026",
    title: "Clover Seeds recall due to undeclared allergens",
    tier: "NO_MATCH",
    decision: "SILENT",
    reason: "Product not stocked; not used in café",
    alert_url: "https://www.food.gov.uk/news-alerts/alert/fsa-prin-39-2026"
  },
  {
    id: "FSA-AA-55-2020",
    title: "Waitrose & Partners recalls Chocolate Mini Cupcakes 9s because of undeclared walnuts",
    tier: "POSSIBLE",
    decision: "ESCALATE",
    reason: "Waitrose product with undeclared walnuts; café serves walnut brownie",
    alert_url: "https://www.food.gov.uk/news-alerts/alert/fsa-aa-55-2020",
    action_pack: {
      owner_notice: "Waitrose cupcakes recalled for undeclared walnuts. We use walnuts in our brownie. Check if we source from Waitrose.",
      customer_notice: "We are reviewing a walnut allergen recall. If you have walnut allergies and recently purchased our walnut brownie, please contact us.",
      stock_action: "Review walnut brownie ingredients and supplier",
      follow_up: "Confirm our walnut supplier is not Waitrose"
    }
  },
  {
    id: "FSA-AA-42-2026",
    title: "Tesco recalls Coleslaw with undeclared mustard",
    tier: "POSSIBLE",
    decision: "ESCALATE",
    reason: "Café handles mustard; Tesco coleslaw not stocked but mustard used",
    alert_url: "https://www.food.gov.uk/news-alerts/alert/fsa-aa-42-2026",
    action_pack: {
      owner_notice: "Tesco coleslaw recalled for undeclared mustard. We handle mustard. Verify our mustard supply chain.",
      customer_notice: "We are reviewing a mustard allergen recall affecting prepared foods.",
      stock_action: "Check mustard ingredient sources",
      follow_up: "Confirm no Tesco products in use"
    }
  },
  {
    id: "FSA-AA-38-2026",
    title: "PepsiCo recalls Doritos Chilli Heatwave because of undeclared milk",
    tier: "LIKELY",
    decision: "ESCALATE",
    reason: "Exact stocked product; batch unknown but café sells this specific item",
    alert_url: "https://www.food.gov.uk/news-alerts/alert/fsa-aa-38-2026",
    action_pack: {
      owner_notice: "URGENT: Doritos Chilli Heatwave recalled for undeclared milk. We stock this exact product. Check batch codes immediately.",
      customer_notice: "We are withdrawing Doritos Chilli Heatwave from sale due to a milk allergen recall. If you purchased this item and have a milk allergy, please return for a full refund.",
      stock_action: "Remove all Doritos Chilli Heatwave from display; check batch codes",
      follow_up: "Contact PepsiCo for affected batch confirmation"
    }
  }
];

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
        tier: alert.tier
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
          mode: "disabled"
        }
      });
    }
  });
  
  state.demoRun = true;
  exportCsvBtn.disabled = false;
  exportHtmlBtn.disabled = false;
  
  showFeedback("Replay complete: 5 alerts assessed, 2 handled quietly, 3 escalated for owner review.", "success");
  updateUI();
  switchView("inbox");
}

// Record owner decision
function recordDecision(alertId, choice, editedPack = null) {
  const alert = state.alerts.find(a => a.id === alertId);
  if (!alert || alert.ownerDecision) return;
  
  const timestamp = new Date().toISOString();
  const pack = editedPack || alert.action_pack;
  
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
  const cutoff = new Date();
  cutoff.setHours(23, 59, 59);
  
  state.diary = {
    timestamp,
    entry_date: new Date().toISOString().split("T")[0],
    summary: "Daily safety record prepared. Opening and closing status await explicit owner confirmation.",
    evidence_cutoff: cutoff.toISOString()
  };
  
  state.auditLog.push({
    timestamp,
    event: "diary_filed",
    entry_date: state.diary.entry_date,
    summary: state.diary.summary
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
    cycleStatus.textContent = `Last replay: COMMITTED · 5 retrieved · 2 silent · 3 escalated. ${new Date().toISOString()}`;
    
    awsEvidence.hidden = false;
  } else {
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
        <a href="#audit" onclick="switchView('audit')">See the audit trail →</a>
      </div>
    `;
    return;
  }
  
  inboxContent.innerHTML = pending.map(alert => `
    <article class="card tier-${alert.tier}">
      <div class="card-top">
        <span class="chip ${alert.tier}">${alert.tier}</span>
        <span>Awaiting your decision</span>
      </div>
      <h2>${alert.reason}</h2>
      <p>${alert.title}</p>
      <a href="${alert.alert_url}" target="_blank" rel="noopener noreferrer">Read the FSA source ↗</a>
      <p class="muted">Injected demonstration draft · Simulated matcher</p>
      <dl>
        <dt>Owner Notice</dt><dd>${alert.action_pack.owner_notice}</dd>
        <dt>Customer Notice</dt><dd>${alert.action_pack.customer_notice}</dd>
        <dt>Stock Action</dt><dd>${alert.action_pack.stock_action}</dd>
        <dt>Follow Up</dt><dd>${alert.action_pack.follow_up}</dd>
      </dl>
      <div class="decision-buttons">
        <button class="primary-btn" onclick="recordDecision('${alert.id}', 'approve')">Approve draft</button>
        <button class="secondary" onclick="toggleEdit('${alert.id}')">Edit draft</button>
        <button class="secondary" onclick="recordDecision('${alert.id}', 'decline')">Decline</button>
      </div>
      <div id="edit-${alert.id}" class="edit-form" style="display: none;">
        <h3>Edit action pack</h3>
        <label for="pack-${alert.id}">Edited JSON (modify values below)</label>
        <textarea id="pack-${alert.id}" rows="12">${JSON.stringify(alert.action_pack, null, 2)}</textarea>
        <button onclick="submitEdit('${alert.id}')">Record edited draft</button>
        <p class="form-error" id="error-${alert.id}"></p>
      </div>
    </article>
  `).join("");
}

// Toggle edit form
function toggleEdit(alertId) {
  const form = document.getElementById(`edit-${alertId}`);
  form.style.display = form.style.display === "none" ? "block" : "none";
}

// Submit edit
function submitEdit(alertId) {
  const textarea = document.getElementById(`pack-${alertId}`);
  const errorEl = document.getElementById(`error-${alertId}`);
  
  try {
    const pack = JSON.parse(textarea.value);
    if (!pack.owner_notice || !pack.customer_notice || !pack.stock_action || !pack.follow_up) {
      throw new Error("All four fields required: owner_notice, customer_notice, stock_action, follow_up");
    }
    recordDecision(alertId, "edit", pack);
  } catch (e) {
    errorEl.textContent = "Invalid JSON: " + e.message;
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
        <span class="chip">${row.event.replace(/_/g, " ")}</span>
        <time>${new Date(row.timestamp).toLocaleString("en-GB")}</time>
      </div>
      <h2>${row.alert_title || (row.entry_date ? "Daily diary · " + row.entry_date : "Event")}</h2>
      ${row.reason ? `<p>${row.reason}</p>` : ""}
      ${row.tier ? `<p>Tier: ${row.tier} · Gate: ${row.decision}</p>` : ""}
      ${row.owner_decision ? `<p><b>Owner choice: ${row.owner_decision.decision.toUpperCase()}</b></p>` : ""}
      ${row.notification ? `<p>Notification: ${row.notification.outcome} · ${row.notification.provider} · ${row.notification.mode}. Provider acceptance does not prove inbox receipt.</p>` : ""}
      <details>
        <summary>Inspect stored evidence</summary>
        <pre>${JSON.stringify(row, null, 2)}</pre>
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
    .filter(a => a.ownerDecision)
    .map(a => ({
      alert_id: a.id,
      alert_title: a.title,
      state: a.ownerDecision.decision.toUpperCase()
    }));
  
  diaryContent.innerHTML = `
    <article class="card">
      <h2>Original filing</h2>
      <p>${state.diary.summary}</p>
      <p>Opening: <b>${state.diaryConfirmation ? state.diaryConfirmation.opening_status : "unconfirmed"}</b> · Closing: <b>${state.diaryConfirmation ? state.diaryConfirmation.closing_status : "unconfirmed"}</b></p>
      <p class="muted">Evidence cutoff: ${new Date(state.diary.evidence_cutoff).toLocaleString("en-GB")}</p>
      
      ${state.diaryConfirmation ? `
        <h2>Stored owner confirmation</h2>
        <p>Opening: ${state.diaryConfirmation.opening_status} · Closing: ${state.diaryConfirmation.closing_status}</p>
        <p>${state.diaryConfirmation.note}</p>
        <p class="muted">Mode: ${state.diaryConfirmation.mode}. Stored first answers retained.</p>
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
      <h2>Linked recall decisions</h2>
      ${linkedRecalls.length > 0 ? linkedRecalls.map(link => `
        <article class="card">
          <span class="chip">${link.state}</span>
          <h3>${link.alert_title}</h3>
          <p class="muted">${link.alert_id}</p>
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
    <h2>${state.business.name}</h2>
    <p>Handled allergens: ${state.business.handled_allergens.join(", ")}</p>
    
    ${state.business.inventory.map(item => `
      <article class="card">
        <h2>${item.name}</h2>
        <p>${item.kind}${item.brand ? " · " + item.brand : ""}</p>
        <dl>
          <dt>Ingredients</dt><dd>${item.ingredients.join(", ") || "None recorded"}</dd>
          <dt>Allergens</dt><dd>${item.allergens.join(", ") || "None recorded"}</dd>
          <dt>Supplier</dt><dd>${item.supplier || "None recorded"}</dd>
          <dt>Batch codes</dt><dd>${item.batch_codes.join(", ") || "Unknown"}</dd>
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

// Export CSV
function exportCsv() {
  if (state.auditLog.length === 0) return;
  
  const headers = ["timestamp", "event", "alert_id", "alert_title", "tier", "decision", "reason"];
  const rows = [headers.join(",")];
  
  rows.push("# PUBLIC BROWSER SIMULATION - NOT PRODUCTION DATA");
  rows.push("");
  
  state.auditLog.forEach(row => {
    const values = headers.map(h => {
      const val = row[h] || "";
      return typeof val === "string" ? `"${val.replace(/"/g, '""')}"` : val;
    });
    rows.push(values.join(","));
  });
  
  const csv = rows.join("\n");
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
<p>Generated: ${new Date().toLocaleString("en-GB")}</p>
<p>Session: ${state.business.name}</p>

${state.auditLog.map(row => `
<div class="event">
<div class="meta">${new Date(row.timestamp).toLocaleString("en-GB")} · ${row.event.replace(/_/g, " ")}</div>
<h2>${row.alert_title || (row.entry_date ? "Daily diary · " + row.entry_date : "Event")}</h2>
${row.reason ? `<p>${row.reason}</p>` : ""}
${row.tier ? `<p>Tier: ${row.tier} · Gate: ${row.decision}</p>` : ""}
${row.owner_decision ? `<p><strong>Owner choice: ${row.owner_decision.decision.toUpperCase()}</strong></p>` : ""}
<details>
<summary>Full record</summary>
<pre>${JSON.stringify(row, null, 2)}</pre>
</details>
</div>
`).join("")}

<footer style="margin-top: 3rem; padding-top: 2rem; border-top: 1px solid #E3E9EC; color: #55666E;">
<p>AllerGuard · Public demonstration · ${new Date().getFullYear()}</p>
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
