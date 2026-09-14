const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
function session() {
  const elements = new Map();
  function element() {
    return {innerHTML:'',textContent:'',value:'',hidden:true,focus(){},classList:{add(){},remove(){}},addEventListener(){},setAttribute(){},removeAttribute(){}};
  }
  const context=vm.createContext({
    document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},querySelectorAll(){return [];},createElement:element},
    Intl, Date, structuredClone, setTimeout(){}, Blob, URL
  });
  for(const path of ['pages-demo/data.js','pages-demo/app.js'])vm.runInContext(fs.readFileSync(path,'utf8'),context);
  return code=>vm.runInContext(code,context);
}
test('replay preserves first owner choices and event totals',()=>{
  const run=session();run('startFresh();runReplay()');
  assert.equal(run('state.auditLog.length'),11);
  run("recordDecision('FSA-AA-55-2020','approve');recordDecision('FSA-AA-55-2020','decline');runReplay()");
  assert.equal(run('state.auditLog.length'),12);
  assert.equal(run("state.alerts.find(a=>a.id==='FSA-AA-55-2020').ownerDecision.decision"),'approve');
  assert.equal(run('state.lastCycle.status'),'EMPTY');
  assert.equal(run('state.alerts.filter(a=>a.decision===\'SILENT\').length'),2);
});
test('edit rejects incomplete or unsafe packs without appending evidence',()=>{
 const run=session();run('startFresh();runReplay()');
 assert.throws(()=>run("recordDecision('FSA-AA-42-2026','edit',{})"));
 assert.throws(()=>run("validatePack({...REPLAY_ALERTS[2].action_pack,customer_notice:'Sent to customers'})"));
 assert.equal(run('state.auditLog.length'),11);
});
test('diary filing and explicit confirmation are separate first-write records',()=>{
 const empty=session();empty('startFresh();fileDiary()');
 assert.equal(empty('exportCsvBtn.disabled'),false);
 const run=session();run('startFresh();runReplay();fileDiary()');
 const original=run('JSON.stringify(state.diary)');
 run("confirmDiary('exception','confirmed','')");
 assert.equal(run('state.diaryConfirmation'),null);
 run("confirmDiary('confirmed','confirmed','');confirmDiary('exception','exception','late');fileDiary();runReplay()");
 assert.equal(run('state.auditLog.length'),13);
 assert.equal(run('state.diaryConfirmation.opening_status'),'confirmed');
 assert.equal(run('JSON.stringify(state.diary)'),original);
 assert.equal(run("londonDate(new Date('2026-09-13T23:30:00Z'))"),'2026-09-14');
});
test('CSV has one rectangular evidence row per event and retains edited payloads',()=>{
 const run=session();run('startFresh();runReplay()');
 run("recordDecision('FSA-AA-42-2026','edit',{...REPLAY_ALERTS[3].action_pack,staff_note:'Hold, check \"batch\"\\nwith owner'});fileDiary();confirmDiary('confirmed','confirmed','')");
 const csv=run('buildCsv()');
 assert.match(csv,/PUBLIC BROWSER SIMULATION/);
 assert.match(csv,/owner_choice/);
 assert.match(csv,/display_time/);
 assert.doesNotMatch(csv,/raw_timestamp/);
 assert.doesNotMatch(csv,/payload_json/);
 assert.match(csv,/Hold, check/);
 assert.match(csv,/Diary confirmation recorded/);
 assert.equal(csv.split('\r\n').length,run('state.auditLog.length')+1);
});
test('inline event handlers cannot return under the strict public CSP',()=>{
 const source=fs.readFileSync('pages-demo/app.js','utf8');
 assert.doesNotMatch(source,/\bon(?:click|submit|load|error)\s*=/i);
 assert.match(fs.readFileSync('pages-demo/_headers','utf8'),/connect-src 'none'/);
});
test('structured inspect and edit keep simulation evidence intact',()=>{
  const run=session();
  run('startFresh();runReplay()');
  assert.match(run('inboxContent.innerHTML'),/Review and edit draft/);
  assert.doesNotMatch(run('inboxContent.innerHTML'),/Edited JSON/);
  assert.doesNotMatch(run('inboxContent.innerHTML'),/id="pack-/);
  run('renderAudit()');
  assert.doesNotMatch(run('auditContent.innerHTML'),/Technical record/);
  assert.doesNotMatch(run('auditContent.innerHTML'),/<pre/);
  assert.match(run('auditContent.innerHTML'),/No recorded match/);
  assert.match(run('auditContent.innerHTML'),/Handled quietly/);
  const before=run('state.auditLog.length');
  run("submitEdit('FSA-AA-42-2026')");
  assert.equal(run('state.auditLog.length'),before);
  run("cancelEdit('FSA-AA-42-2026')");
  assert.equal(run('state.auditLog.length'),before);
  run(`(() => {
    const pack = REPLAY_ALERTS.find(a => a.id === 'FSA-AA-42-2026').action_pack;
    document.getElementById('pull-FSA-AA-42-2026').value = pack.pull;
    document.getElementById('staff-FSA-AA-42-2026').value = pack.staff_note + ' extra';
    document.getElementById('notice-FSA-AA-42-2026').value = pack.customer_notice;
    document.getElementById('sub-FSA-AA-42-2026').value = pack.substitution;
  })()`);
  const serialized=JSON.parse(run("JSON.stringify(packFromForm('FSA-AA-42-2026'))"));
  assert.equal(serialized.staff_note.endsWith(' extra'), true);
  run("submitEdit('FSA-AA-42-2026')");
  assert.equal(run('state.auditLog.length'),before+1);
  const source=fs.readFileSync('pages-demo/app.js','utf8');
  assert.match(source,/packFromForm/);
  assert.doesNotMatch(source,/JSON\.parse\(textarea/);
});
test('London display times hide ISO and keep BST or GMT',()=>{
 const run=session();
 assert.equal(run("formatDisplayTime('2026-09-14T10:51:12.262Z')"),'14 Sep 2026, 11:51 BST');
 assert.equal(run("formatDisplayTime('2026-01-14T10:51:00.000Z')"),'14 Jan 2026, 10:51 GMT');
 assert.equal(run("formatDisplayDate('2026-09-14')"),'14 Sep 2026');
});
test('HTML export is branded, structured and free of JSON, hashes and ISO stamps',()=>{
 const run=session();
 run('startFresh();runReplay()');
 run("recordDecision('FSA-AA-55-2020','approve');fileDiary()");
 const html=run('buildHtml()');
 assert.match(html,/Interactive replay demo · synthetic business · simulated notifications/);
 assert.match(html,/#f4f1ea/i);
 assert.match(html,/#2f4cb0/i);
 assert.match(html,/Alert reference/);
 assert.match(html,/Assessment result/);
 assert.match(html,/Gate result/);
 assert.match(html,/Owner choice/);
 assert.match(html,/Recorded time/);
 assert.match(html,/No customer communication or stock action was executed/);
 assert.match(html,/14 Sep 2026,/);
 assert.doesNotMatch(html,/<pre/i);
 assert.doesNotMatch(html,/Technical record/);
 assert.doesNotMatch(html,/payload_json/);
 assert.doesNotMatch(html,/\d{4}-\d{2}-\d{2}T/);
 assert.doesNotMatch(html,/#216e59|#f3f5ee|#183c34|#28a745|#198754|#2e7d32/i);
 assert.doesNotMatch(html,/[0-9a-f]{64}/i);
});
test('Pages shell has no green theme tokens and keeps the public CSP',()=>{
 const css=fs.readFileSync('pages-demo/styles.css','utf8');
 const html=fs.readFileSync('pages-demo/index.html','utf8');
 assert.match(html,/PUBLIC INTERACTIVE DEMO/);
 assert.match(html,/Public interactive demo/);
 assert.match(html,/How AllerGuard works/);
 assert.match(html,/Safety boundaries/);
 assert.match(html,/This session/);
 assert.match(css,/#f4f1ea/i);
 assert.match(css,/#2f4cb0/i);
 assert.doesNotMatch(css,/#216e59|#f3f5ee|#183c34|#28a745|#198754|#2e7d32|#1a7f4c/i);
 assert.match(fs.readFileSync('pages-demo/_headers','utf8'),/connect-src 'none'/);
});
