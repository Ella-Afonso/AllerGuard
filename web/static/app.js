"use strict";
const feedback = document.querySelector("#feedback");
let busy = false;
async function send(path, payload = {}) {
  if (busy) return;
  busy = true;
  feedback.textContent = "Recording…";
  try {
    const response = await fetch(path, {method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json",
        "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content},
      body: JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || ("Cycle " + (result.status || "failed") + "; inspect evidence before retrying."));
    feedback.textContent = result.message || ("Cycle " + result.status + ". Refreshing stored evidence…");
    window.location.reload();
  } catch (error) {
    feedback.textContent = error.message;
    throw error;
  } finally { busy = false; }
}
function packFromForm(form) {
  return {
    pull: form.elements.pull.value,
    staff_note: form.elements.staff_note.value,
    customer_notice: form.elements.customer_notice.value,
    substitution: form.elements.substitution.value
  };
}
document.querySelectorAll("[data-post]").forEach(button => {
  button.addEventListener("click", () => send(button.dataset.post).catch(() => {}));
});
document.querySelectorAll("[data-decision]").forEach(button => {
  button.addEventListener("click", () => send("/api/decisions", {
    escalation_id: button.dataset.id, choice: button.dataset.decision
  }).catch(() => {}));
});
document.querySelectorAll("[data-edit]").forEach(button => {
  button.addEventListener("click", () => {
    const form = document.getElementById("edit-" + button.dataset.edit);
    form.hidden = !form.hidden;
    if (!form.hidden) form.querySelector("[name=pull]").focus();
  });
});
document.querySelectorAll("[data-cancel-edit]").forEach(button => {
  button.addEventListener("click", () => {
    const form = button.closest("form");
    form.reset();
    form.querySelector(".form-error").textContent = "";
    form.hidden = true;
  });
});
document.querySelectorAll(".edit-form").forEach(form => {
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const error = form.querySelector(".form-error");
    error.textContent = "";
    try {
      await send("/api/decisions", {escalation_id: form.dataset.id, choice: "edit",
        pack: packFromForm(form)});
    } catch (failure) { error.textContent = failure.message; }
  });
});
const diary = document.querySelector("#diary-confirm");
if (diary) diary.addEventListener("submit", async event => {
  event.preventDefault();
  try {
    await send("/api/diary/confirm", {opening_status: diary.elements.opening_status.value,
      closing_status: diary.elements.closing_status.value, note: diary.elements.note.value,
      mode: "simulated"});
  } catch (failure) { diary.querySelector(".form-error").textContent = failure.message; }
});
