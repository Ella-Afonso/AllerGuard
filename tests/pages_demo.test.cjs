const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
function session() {
  const elements = new Map();
  function element() {
    return {innerHTML:'',textContent:'',classList:{add(){},remove(){}},addEventListener(){},setAttribute(){},removeAttribute(){}};
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
 assert.match(csv,/original_pack/);
 assert.match(csv,/Hold, check/);
 assert.match(csv,/diary_confirmed/);
 assert.equal(csv.split('\r\n').length,run('state.auditLog.length')+1);
});
test('inline event handlers cannot return under the strict public CSP',()=>{
 const source=fs.readFileSync('pages-demo/app.js','utf8');
 assert.doesNotMatch(source,/\bon(?:click|submit|load|error)\s*=/i);
 assert.match(fs.readFileSync('pages-demo/_headers','utf8'),/connect-src 'none'/);
});
