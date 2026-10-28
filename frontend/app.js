'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icons = {
  overview:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  ship:'<path d="m3 15 9 4 9-4-2 6H5zM6 14V7h12v7M10 7V3h4v4M3 23q2-2 4 0 2-2 5 0 3-2 5 0 2-2 4 0"/>',
  upload:'<path d="M12 16V3m-4 4 4-4 4 4M4 14v6a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-6"/>',
  shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9S4 17 4 12V6z"/><path d="m8 12 3 3 5-6"/>',
  link:'<path d="m10 13 4-4M8 15l-2 2a4 4 0 0 1-5-5l4-4a4 4 0 0 1 5 0m4 1 2-2a4 4 0 0 1 5 5l-4 4a4 4 0 0 1-5 0"/>',
  logout:'<path d="M10 4H4v16h6m4-12 4 4-4 4m-6-4h10"/>',
  bell:'<path d="M5 16h14l-2-3V9a5 5 0 0 0-10 0v4zM10 20h4"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
  warning:'<path d="m12 3 10 18H2zM12 9v5m0 3v.1"/>',
  file:'<path d="M13 3H5v18h14V9zM13 3v6h6M8 13h8m-8 4h6"/>',
  database:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  check:'<path d="m5 12 4 4L19 6"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const states = ['Awaiting arrival','In clearing','In delivery','Delivered','Completed'];
const names = {overview:'Overview',shipments:'Shipments',imports:'Import centre',qac:'QAC review',actions:'Import Officer desk'};
const fields = {pre_alert:'Pre-alert',eta:'ETA',berth:'Actual berth · ATA/ATD',paar:'PAAR received',obl:'OBL received',assessment:'Final assessment received',duty_receipt:'Duty receipt',exam:'Customs examination',customs_release:'Customs release',do:'Shipping release · DO',tdo:'Terminal Delivery Order',gate_out:'Gate-out',warehouse:'Factory / warehouse arrival',terminal_validity:'Terminal validity',ecd:'ECD received'};
const sourceHeaders = ['S/N','Pre-alert date','Item description','BOL number','Terminal','Shipping line','ETA','ATD · GZI actual berth','Container count','Container size','PAAR date','OBL received','Assessment date','SGD number','Duty received date','Customs exam','Customs release','Shipping release / DO','TDO','Gate-out','Factory arrival (check section header)','Comments','File handler','Remark','Terminal validity','PCA Final Closure','ECD','Clearing income','Haulage income','Projected total income','Clearing cost','Haulage cost','Projected total expenses','Projected profit'];
const state = {page:'overview',client:'',filter:'',search:'',issues:false,pageNumber:1,clients:[],batches:[],overview:null,csrf:null,batch:null,previewPage:1,previewIssues:false,detail:null,version:0,deskQueue:'all',deskTeam:'',deskStatus:''};
let searchTimer, toastTimer, detailVersion = 0, tableVersion = 0;

function date(value) { if (!value) return 'Not recorded'; return new Date(value+'T12:00:00').toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric'}); }
function number(value) { return Number(value || 0).toLocaleString('en-GB'); }
function initials(value) { return value ? value.split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase() : '—'; }
function warnings(record) { return (record.issues || []).filter(x=>x.severity==='warning'); }
function pill(value) { return `<span class="state-pill stage-${states.indexOf(value)}">${esc(value)}</span>`; }
function paintIcons(root=document) { $$('[data-icon]',root).forEach(x=>x.innerHTML=icon(x.dataset.icon)); }
function syncSidebar() { const open=$('#sidebar').classList.contains('open');$('#sidebar').inert=matchMedia('(max-width:680px)').matches&&!open;$('#mobile-menu').setAttribute('aria-expanded',String(open)); }
function toast(message) { clearTimeout(toastTimer); $('#toast').textContent=message; $('#toast').hidden=false; toastTimer=setTimeout(()=>$('#toast').hidden=true,4500); }
async function api(path, body) {
  const options = {credentials:'same-origin',headers:{}};
  if (body !== undefined) { options.method='POST'; options.headers={'Content-Type':'application/json','X-CSRF-Token':state.csrf || ''}; options.body=JSON.stringify(body); }
  const response = await fetch(path,options);
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    if (response.status===401 && state.csrf) {state.csrf=null; await showAuth();}
    throw new Error(payload.error || 'The request could not be completed.');
  }
  return payload;
}
function notice(text, warning=false) { return `<div class="notice ${warning?'warning':''}">${icon(warning?'warning':'info')}<span>${text}</span></div>`; }
function empty(title,text,action='imports',button='Preview a report',symbol='ship') {
  return `<div class="empty-state"><div class="empty-icon">${icon(symbol)}</div><h3>${esc(title)}</h3><p>${esc(text)}</p>${action?`<button class="button primary" data-go="${action}">${esc(button)} ${icon('arrow')}</button>`:''}</div>`;
}

async function showAuth() {
  const session = await api('/api/session');
  state.configured = session.configured;
  $('#boot').hidden=true;
  if (session.authenticated) { state.csrf=session.csrf; $('#auth-screen').hidden=true; $('#app').hidden=false; return start(); }
  $('#app').hidden=true; $('#auth-screen').hidden=false;
  $('#auth-title').textContent=session.configured?'Welcome back.':'Your workspace starts here.';
  $('#auth-description').textContent=session.configured?'Sign in to your local shipment register.':'Create owner access before working with private shipment records.';
  $('#auth-submit').innerHTML=(session.configured?'Sign in':'Create owner access')+' '+icon('arrow');
  $('#confirm-wrap').hidden=session.configured;
  $('#confirm-password').required=!session.configured;
  $('#password').autocomplete=session.configured?'current-password':'new-password';
}

$('#auth-form').addEventListener('submit', async event=>{
  event.preventDefault(); $('#auth-error').textContent='';
  if (!state.configured && $('#password').value!==$('#confirm-password').value) {$('#auth-error').textContent='Passwords do not match.'; return;}
  const button=$('#auth-submit'); button.disabled=true;
  try {
    const result=await api(state.configured?'/api/auth/login':'/api/auth/setup',{password:$('#password').value});
    state.csrf=result.csrf; $('#auth-form').reset(); $('#auth-screen').hidden=true; $('#app').hidden=false; await start();
  } catch(error) {$('#auth-error').textContent=error.message;} finally {button.disabled=false;}
});

async function refreshMeta() {
  const [clients,batches,overview]=await Promise.all([api('/api/clients'),api('/api/imports'),api('/api/overview')]);
  state.clients=clients.clients; state.batches=batches.imports; state.overview=overview;
  $('#nav-total').textContent=number(overview.total); $('#nav-qac').textContent=number(overview.rows_with_issues);
  $('#nav-imports').textContent=number(batches.imports.filter(x=>x.status==='preview').length);
  $('#sidebar-clients').innerHTML=state.clients.map(c=>`<button class="client-nav ${state.client===String(c.id)?'selected':''}" data-client="${c.id}"><span class="client-dot"></span>${esc(c.name)}<small>${number(c.shipment_count)}</small></button>`).join('');
}
async function start() { await refreshMeta(); await render(); }
async function navigate(page,client=state.client) {
  state.page=page; state.client=client; state.filter=''; state.search=''; state.pageNumber=1; state.issues=false;
  $('#sidebar').classList.remove('open'); syncSidebar(); await render();
}
function heading() {
  const text={overview:['Shipment overview','Track the whole journey. Know what needs your attention.'],shipments:['Shipment register','Every client, every milestone, in one shared register.'],imports:['Import centre','Preview first. Keep the source. Apply only what you have reviewed.'],actions:['Import Officer desk','Coordinate the job. See the next action, responsible team and response you are waiting for.'],qac:['QAC review queue','Review inconsistencies before they become operational assumptions.']};
  return `<div class="page-heading"><div><span class="eyebrow">LIBRA CIRCLE / CLEARING OPERATIONS</span><h1>${text[state.page][0]}</h1><p>${text[state.page][1]}</p></div><div class="heading-actions"><button class="button secondary" data-go="${state.page==='imports'?'shipments':'imports'}">${icon(state.page==='imports'?'ship':'file')}${state.page==='imports'?'View register':'Import history'}</button>${state.page!=='imports'?`<button class="button primary" id="new-job">+ Create shipment</button>`:''}</div></div>`;
}
function tabs() {
  return `<div class="context-strip"><div class="client-tabs"><button class="client-tab ${!state.client?'active':''}" data-client="">All clients</button>${state.clients.map(c=>`<button class="client-tab ${state.client===String(c.id)?'active':''}" data-client="${c.id}">${esc(c.name)}<span class="tab-number">${number(c.shipment_count)}</span></button>`).join('')}</div><span class="test-badge">TEST WORKSPACE</span></div>`;
}
function cards(overview) {
  const notes=['Berthing not recorded','Reported arrival','Movement / delivery','All at warehouse / source proposals','Closure confirmed'];
  return `<div class="state-grid">${states.map((s,i)=>`<button class="state-card stage-${i} ${state.filter===s?'selected':''}" data-state="${s}"><span class="card-label"><i class="state-dot"></i>${s}</span><strong class="card-number">${number(overview.states[s])}</strong><span class="card-foot">${notes[i]}${icon('arrow')}</span></button>`).join('')}</div>`;
}
async function render() {
  const version=++state.version; $('#breadcrumb').textContent=names[state.page];
  $$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.page===state.page));
  $$('.client-nav').forEach(b=>b.classList.toggle('selected',b.dataset.client===state.client));
  $('#main').innerHTML=heading()+`<div class="panel"><div class="skeleton" aria-label="Loading workspace"></div></div>`;
  try {
    if (state.page==='actions') {await renderActions(version);return;}
    if (state.page==='imports') {
      const data=await api('/api/sources'); if(version!==state.version) return;
      renderImports(data.sources); return;
    }
    const query=new URLSearchParams(); if(state.client)query.set('client_id',state.client);
    const overview=await api('/api/overview?'+query); if(version!==state.version)return;
    const top=heading()+tabs()+(state.page==='qac'?notice(`${number(overview.rows_with_issues)} records have review findings. A finding describes a source-data question, not confirmed noncompliance.`,true):cards(overview));
    $('#main').innerHTML=top+(state.page==='overview'?`<section class="desk-home"><div class="panel-title">Your coordination desk</div><p class="detail-note">You own the job. Teams own their next actions. Reminders stay with the owner.</p>${deskCards(overview.queue_counts,true)}</section>`:'')+`<div id="register-panel" class="panel"></div>`+(state.page==='overview'?lowerPanels(): '');
    await loadTable(version);
  } catch(error) { if(version===state.version)$('#main').innerHTML=heading()+`<div class="inline-error" role="alert">${esc(error.message)}<br><button class="button secondary" id="retry-load">Try again</button></div>`; }
}
function lowerPanels() {
  return `<div class="lower-grid"><section class="panel"><div class="panel-header"><div class="panel-title">Recent imports</div><button class="text-link" data-go="imports">View all ${icon('arrow')}</button></div><div class="small-panel-body">${state.batches.length?state.batches.slice(0,3).map(b=>`<div class="import-row"><span class="file-icon">${icon('file')}</span><div><strong>${esc(b.filename)}</strong><small>${esc(b.client_name)} · ${number(b.summary.shipments)} shipments · ${b.report_date?'Cut-off '+date(b.report_date):'Cut-off not supplied'}</small></div><button class="badge ${b.status==='preview'?'preview':''}" data-batch="${b.id}">${b.status==='preview'?'Review preview':'Applied to test'}</button></div>`).join(''):'<div class="import-row"><span class="file-icon">'+icon('file')+'</span><div><strong>No reports imported yet</strong><small>Your originals and import history will appear here.</small></div></div>'}</div></section><section class="panel"><div class="panel-header"><div class="panel-title">Workspace connections</div><span class="count-tag">SLICE 2</span></div><div class="small-panel-body"><div class="connection-row"><span>${icon('database')}Shipment API</span><span class="connection-state on">Connected locally</span></div><div class="connection-row"><span>${icon('link')}Hermes fleet</span><span class="connection-state">Not connected</span></div><div class="connection-row"><span>${icon('bell')}Telegram & reminders</span><span class="connection-state">Delivery disabled</span></div></div></section></div>`;
}
async function loadTable(version=state.version) {
  const ticket=++tableVersion;
  const query=new URLSearchParams({page:state.pageNumber,limit:12});
  if(state.client)query.set('client_id',state.client); if(state.filter)query.set('state',state.filter);
  if(state.search)query.set('search',state.search); if(state.issues||state.page==='qac')query.set('issues','1');
  const result=await api('/api/shipments?'+query); if(version!==state.version||ticket!==tableVersion)return;
  const panel=$('#register-panel'); if(!panel)return;
  const title=state.page==='qac'?'Records to review':'Shipment register';
  panel.innerHTML=`<div class="panel-header"><div><div class="panel-title">${title}<span class="count-tag">${number(result.total)}</span></div><p class="panel-subtitle">${state.filter?esc(state.filter)+' · ':''}Owner records & historical proposals · test register</p></div><span class="report-label">${state.overview.total?'Source cut-off may be unknown':'Start with your GZI report'}</span></div><div class="table-toolbar"><div class="filter-tabs"><button class="filter-tab ${!state.issues?'active':''}" data-issues="0">${state.page==='qac'?'All findings':'All shipments'}</button>${state.page!=='qac'?`<button class="filter-tab ${state.issues?'active':''}" data-issues="1">Needs review</button>`:''}</div><div class="search-box"><span>${icon('search')}</span><input id="shipment-search" type="search" placeholder="Search BL, client, officer or agent…" aria-label="Search shipments" value="${esc(state.search)}"></div></div>${result.total?shipmentTable(result.shipments):empty(state.search||state.filter||state.issues?'No matching shipments':'Your register is ready',state.search||state.filter||state.issues?'Try another search, state or client filter.':'Preview the GZI report, review the findings, then apply it to your test register.',state.search||state.filter||state.issues?'':'imports')}${result.total?`<div class="table-footer"><span>Showing ${(result.page-1)*result.limit+1}–${Math.min(result.page*result.limit,result.total)} of ${number(result.total)} shipments</span><div class="pagination"><button class="page-button" data-page-turn="-1" ${result.page<=1?'disabled':''}>← Previous</button><span class="page-button active">${result.page}</span><button class="page-button" data-page-turn="1" ${result.page*result.limit>=result.total?'disabled':''}>Next →</button></div></div>`:''}`;
}
function shipmentTable(records,preview=false) {
  return `<div class="table-scroll"><table class="shipments-table"><thead><tr><th>Shipment / bill of lading</th><th>Client</th><th>Terminal / line</th><th>Containers</th><th>Reported stage</th><th>Field Agent</th><th>Review</th></tr></thead><tbody>${records.map(r=>`<tr data-${preview?'preview-row':'shipment'}="${preview?r.source_row:r.id}"><td><button class="bl-button" data-${preview?'preview-row':'shipment'}="${preview?r.source_row:r.id}">${esc(r.bl)}</button><span class="cargo-description" title="${esc(r.description)}">${esc(r.description)}</span></td><td><span class="table-client">${esc(r.client_name||state.batch?.client_name||'GZI')}</span></td><td class="terminal-line">${esc(r.terminal||'Not recorded')}<small>${esc(r.liner||'Line unknown')}</small></td><td>${r.container_count?number(r.container_count):'Unknown'}${r.container_size?` × ${esc(r.container_size)}′`:''}</td><td>${pill(r.state||r.proposed_state)}</td><td><span class="handler"><span class="mini-avatar">${esc(initials(r.field_agent??r.handler))}</span>${esc((r.field_agent??r.handler)||'Unassigned')}</span></td><td>${warnings(r).length?`<span class="issue-label">${icon('warning')}${warnings(r).length} ${warnings(r).length===1?'finding':'findings'}</span>`:'<span class="muted">Source only</span>'}</td></tr>`).join('')}</tbody></table></div>`;
}

function renderImports(sources) {
  state.sources=sources;
  $('#main').innerHTML=heading()+notice('Imports stay separate from the register until you review and apply them. Applying here creates test records only; reminders remain off.')+`<div class="upload-layout"><section class="panel"><div class="panel-header"><div class="panel-title">Preview a client report</div><span class="count-tag">CSV</span></div><form id="upload-form" class="upload-form"><label id="drop-zone" class="drop-zone" for="csv-file"><span class="empty-icon">${icon('upload')}</span><strong>Drop a report here, or choose a file</strong><p>UTF-8 CSV · up to 5 MB · original preserved</p><input id="csv-file" name="csv-file" type="file" accept=".csv,text/csv"></label><div class="form-grid"><div class="field"><label for="import-client">Client</label><select id="import-client">${state.clients.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select><small>GZI: recognized headings are mapped in any order. Missing columns stay pending.</small></div><div class="field"><label for="report-date">Reporting cut-off <span class="muted">(optional)</span></label><input id="report-date" type="date"><small>Leave empty if unknown. The filename is not a confirmed cut-off.</small></div></div><p id="import-error" class="form-error" role="alert"></p><button id="upload-submit" type="submit" class="button primary">Build import preview ${icon('arrow')}</button></form></section><section class="panel source-card"><span class="eyebrow">AVAILABLE ON THIS MACHINE</span><h2 class="panel-title">Start with the GZI report</h2><p>Use the supplied source without uploading it again. Available columns are mapped; missing fields stay unknown.</p>${sources.length?sources.map(s=>`<div class="source-file"><strong>${icon('file')}${esc(s.filename)}</strong><small>${number(Math.round(s.size/1024))} KB · GZI mapping · source file</small><button class="button secondary" data-source="${s.id}">Preview this report ${icon('arrow')}</button></div>`).join(''):'<p>No bundled source is available. Choose a CSV to begin.</p>'}<p>The importer keeps repeated BLs separate and highlights ambiguous dates, release gaps and partial-delivery notes.</p></section></div><div id="preview-target"></div><section class="panel"><div class="panel-header"><div class="panel-title">Import history<span class="count-tag">${state.batches.length}</span></div></div><div class="small-panel-body">${state.batches.length?state.batches.map(b=>`<div class="import-row"><span class="file-icon">${icon('file')}</span><div><strong>${esc(b.filename)}</strong><small>${esc(b.client_name)} · ${number(b.summary.shipments)} shipments · ${b.report_date?date(b.report_date):'Unknown cut-off'}</small></div><button class="badge ${b.status==='preview'?'preview':''}" data-batch="${b.id}">${b.status==='preview'?'Open preview':'View applied batch'}</button></div>`).join(''):'<div class="import-row muted">No import previews yet.</div>'}</div></section>`;
  const zone=$('#drop-zone');
  ['dragenter','dragover'].forEach(type=>zone.addEventListener(type,e=>{e.preventDefault();zone.classList.add('drag');}));
  ['dragleave','drop'].forEach(type=>zone.addEventListener(type,e=>{e.preventDefault();zone.classList.remove('drag');}));
  zone.addEventListener('drop',e=>{if(e.dataTransfer.files.length){$('#csv-file').files=e.dataTransfer.files;}});
  $('#upload-form').addEventListener('submit',upload);
  if(state.batch)renderPreview();
}
async function upload(event) {
  event.preventDefault(); const file=$('#csv-file').files[0];
  if(!file){$('#import-error').textContent='Choose a CSV file, or use the available GZI source.';return;}
  if(file.size>5*1024*1024){$('#import-error').textContent='The maximum CSV size is 5 MB.';return;}
  const reader=new FileReader(); reader.onload=()=>preview({filename:file.name,content_base64:reader.result.split(',')[1]});reader.onerror=()=>$('#import-error').textContent='The selected file could not be read.';reader.readAsDataURL(file);
}
async function preview(payload) {
  $('#import-error').textContent=''; const buttons=$$('#upload-form button,[data-source]');buttons.forEach(b=>b.disabled=true);
  const client=$('#import-client').value,cutoff=$('#report-date').value;
  try {
    const result=await api('/api/imports/preview',{...payload,client_id:client,report_date:cutoff||null});
    state.batch=result.batch;state.previewPage=1;state.previewIssues=false;await refreshMeta();
    if(state.page==='imports'){renderImports(state.sources);$('#import-client').value=client;$('#report-date').value=cutoff;$('#preview-target').scrollIntoView({behavior:'smooth',block:'start'});}
    toast(result.reused?'Opened the existing preview. No duplicate batch created.':'Preview ready. No shipment records applied yet.');
  } catch(error){if($('#import-error'))$('#import-error').textContent=error.message;else toast(error.message);} finally {buttons.forEach(b=>b.disabled=false);}
}
async function openBatch(id) {
  const result=await api('/api/imports/'+encodeURIComponent(id));state.batch=result.batch;state.previewPage=1;state.previewIssues=false;
  if(state.page!=='imports'){state.page='imports';await render();}else renderPreview();
  $('#preview-target')?.scrollIntoView({behavior:'smooth',block:'start'});
}
function mappingReport(summary) {
  const mappings=summary.column_mappings;
  if(!mappings)return notice('This saved preview used the earlier mapping. Its snapshot is unchanged. New uploads use available headings.');
  return `<section class="mapping-report"><h3>Mapped columns & pending fields</h3><p class="detail-note">Missing columns and empty values stay unknown. Pending here means data still to supply or review, not proof a document has not been received.</p>${mappings.map(m=>`<details class="mapping-section"><summary>Header row ${m.header_row} · ${esc(m.section)} · ${m.mapped.length} mapped · ${m.pending.length} pending</summary><div class="mapping-grid"><div><h4>Available columns</h4>${m.mapped.map(c=>`<p><strong>${esc(c.header)}</strong> → ${esc(c.label)} <small>(column ${c.column})</small></p>`).join('')}</div><div><h4>Pending / not mapped</h4>${m.pending.map(c=>`<p>${esc(c.label)} <small>· ${esc(c.reason)}</small></p>`).join('')||'<p>All supported columns supplied.</p>'}${m.unmapped.length?`<h4>Other original columns retained</h4>${m.unmapped.map(c=>`<p>Column ${c.column} · ${esc(c.header)}</p>`).join('')}`:''}</div></div></details>`).join('')}${summary.skipped_rows?.length?notice(summary.skipped_rows.map(row=>`Row ${row.source_row}: ${esc(row.reason)}`).join('<br>'),true):''}</section>`;
}
function pendingReport(r) {
  const source=r.source_snapshot||r;
  if(!source.pending_fields?.length)return '';
  const labels=Object.fromEntries((state.batch?.summary?.field_labels?Object.entries(state.batch.summary.field_labels):[]));
  for(const m of source.field_mapping||[])labels[m.field]=m.label;
  const missing=source.missing_columns||[],blank=source.blank_fields||[],unresolved=source.unresolved_fields||[];
  const names=list=>list.map(k=>esc(labels[k]||opFields[k]||({sgd:'C Number / SGD',container_count:'Container count',handler:'File handler'})[k]||k.replaceAll('_',' '))).join(', ');
  return `<section class="detail-section"><h3>Pending source information</h3><p class="detail-note">Original import coverage. Owner updates are shown separately above.</p>${missing.length?`<p class="detail-note"><strong>Columns not supplied / ambiguous:</strong> ${names(missing)}.</p>`:''}${blank.length?`<p class="detail-note"><strong>Columns present, values blank:</strong> ${names(blank)}.</p>`:''}${unresolved.length?`<p class="detail-note"><strong>Values need interpretation:</strong> ${names(unresolved)}.</p>`:''}</section>`;
}
function renderPreview() {
  const target=$('#preview-target');if(!target||!state.batch)return;
  const b=state.batch,s=b.summary; const records=state.previewIssues?b.records.filter(r=>warnings(r).length):b.records;
  const from=(state.previewPage-1)*10, page=records.slice(from,from+10);
  target.innerHTML=`<section class="panel preview-panel"><div class="preview-header"><div><span class="eyebrow">${b.status==='applied'?'APPLIED TO TEST REGISTER':'IMPORT PREVIEW / NOT YET APPLIED'}</span><h2>${esc(b.filename)}</h2><p>${esc(b.client_name)} · GZI heading mapping · ${b.report_date?'Reporting cut-off '+date(b.report_date):'Reporting cut-off unknown'}</p></div>${b.status==='preview'?`<button class="button primary" id="apply-import">Apply to test register ${icon('arrow')}</button>`:`<button class="button secondary" data-go="shipments">View register ${icon('arrow')}</button>`}</div><div class="preview-stats"><div class="preview-stat"><strong>${number(s.shipments)}</strong><span>Shipment rows</span></div><div class="preview-stat"><strong>${number(s.unique_bls)}</strong><span>Distinct BLs</span></div><div class="preview-stat"><strong>${number(s.rows_with_issues)}</strong><span>Records to review</span></div><div class="preview-stat"><strong>${number(s.physical_rows-s.shipments)}</strong><span>Non-shipment rows excluded</span></div></div><div class="source-note">${s.duplicate_groups?`${number(s.duplicate_groups)} repeated-BL group · records will remain separate. `:''}Stages are historical proposals. ECD does not establish Completed; quantities and dates may need review.<br>Excluded: ${Object.entries(s.excluded).map(([k,v])=>`${esc(k)} ${v}`).join(' · ')}</div>${mappingReport(s)}<div class="table-toolbar"><div class="filter-tabs"><button class="filter-tab ${!state.previewIssues?'active':''}" data-preview-issues="0">All source rows</button><button class="filter-tab ${state.previewIssues?'active':''}" data-preview-issues="1">Needs review</button></div><span class="report-label">Click a BL to inspect its source and milestones</span></div>${page.length?shipmentTable(page,true):empty('No review findings','There are no warning-level findings in this selection.','') }<div class="preview-pagination"><span>${records.length?from+1:0}–${Math.min(from+10,records.length)} of ${number(records.length)} records</span><div class="pagination"><button class="page-button" data-preview-page="-1" ${state.previewPage<=1?'disabled':''}>← Previous</button><button class="page-button" data-preview-page="1" ${from+10>=records.length?'disabled':''}>Next →</button></div></div></section><div class="notice warning">${icon('info')}<span>Applying preserves every original value and keeps historical-state warnings. No live reminders or verified release claims will be created.</span></div>`;
}
function confirmApply() {
  const b=state.batch;
  $('#action-content').innerHTML=`<span class="test-badge">TEST REGISTER ONLY</span><h2 id="action-title">Apply ${number(b.summary.shipments)} shipment records?</h2><p>The original report and all findings will be retained. These are historical proposals, not verified live shipment statuses.</p><form id="apply-form"><label><input id="confirm-test" type="checkbox" required><span>I have reviewed the preview and understand this applies records to the test register. Notifications remain disabled.</span></label><p id="apply-error" class="form-error" role="alert"></p><div class="dialog-actions"><button class="button secondary" type="button" data-close-action>Keep reviewing</button><button class="button primary" type="submit">Apply test import</button></div></form>`;
  $('#action-dialog').showModal();
  $('#apply-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=$('button[type=submit]',event.currentTarget);button.disabled=true;
    try {await api('/api/imports/'+b.id+'/apply',{confirm_test_import:true});$('#action-dialog').close();state.batch=null;await refreshMeta();await navigate('overview');toast('Import applied to your test register. All source findings retained.');}
    catch(error){$('#apply-error').textContent=error.message;button.disabled=false;}
  });
}

async function openShipment(id) {
  const version=++detailVersion;
  $('#detail-content').innerHTML='<div class="detail-body"><div class="skeleton" aria-label="Loading shipment"></div></div>';
  if(!$('#detail-dialog').open)$('#detail-dialog').showModal();
  try {const result=await api('/api/shipments/'+encodeURIComponent(id));if(version===detailVersion&&$('#detail-dialog').open){state.detail=result.shipment;renderDetail();}}
  catch(error){if(version===detailVersion)$('#detail-content').innerHTML=`<div class="detail-body"><button class="icon-button" data-close-detail aria-label="Close">${icon('close')}</button><p role="alert">${esc(error.message)}</p></div>`;}
}
function openPreviewRow(row) {
  const record=state.batch?.records.find(r=>r.source_row===Number(row));if(!record)return;
  ++detailVersion;state.detail={...record,client_name:state.batch.client_name,filename:state.batch.filename,report_date:state.batch.report_date,batch_id:state.batch.id,job_id:'Preview · row '+row,history:[{at:state.batch.created_at,actor:'owner',action:'import_preview_created'}]};renderDetail();$('#detail-dialog').showModal();
}
function inputField(name,label,value='',type='text',extra='') {
  return `<div class="field"><label for="edit-${name}">${esc(label)}</label><input id="edit-${name}" name="${name}" type="${type}" value="${esc(value??'')}" ${extra}></div>`;
}
function selectField(name,label,value,options) {
  return `<div class="field"><label for="edit-${name}">${esc(label)}</label><select id="edit-${name}" name="${name}">${options.map(([v,l])=>`<option value="${v}" ${value===v?'selected':''}>${esc(l)}</option>`).join('')}</select></div>`;
}
const requestOptions=[['unknown','Unknown'],['not_requested','Nil · not requested'],['requested','Requested']];
const applicabilityOptions=[['unknown','Unknown'],['required','Required'],['not_applicable','Not applicable · reason required']];
// Approval is a process checkpoint; its date and approver are not captured in the current UI.
const opFields={...fields,client_invoiced:'Client invoiced'};
function commandFooter(label='Save update',exception=true) {
  return `${inputField('reason','Reason / source of this update','','text','required maxlength="500"')}${exception?`<details class="exception-fields"><summary>Reported exception / separate duplicate job</summary><p class="detail-note">Use only to retain an observed fact that conflicts with prerequisites. It stays flagged for review.</p>${inputField('exception_reason','Exception reason')}${inputField('duplicate_reason','Reason for a distinct job sharing this BL')}</details>`:''}<p class="form-error command-error" role="alert"></p><div class="dialog-actions"><button type="submit" class="button primary">${label}</button></div>`;
}
function formValue(form,name) {return form.elements.namedItem(name)?.value||'';}
function dateValues(form) {return Object.fromEntries(Object.keys(opFields).filter(k=>!['gate_out','warehouse'].includes(k)).map(k=>[k,formValue(form,'dates.'+k)||null]));}
function commonCommand(form) {
  return {reason:formValue(form,'reason'),exception_reason:formValue(form,'exception_reason'),duplicate_reason:formValue(form,'duplicate_reason')};
}
async function saveCommand(form,path,body) {
  const button=$('button[type=submit]',form),error=$('.command-error',form);
  button.disabled=true;error.textContent='';
  const signature=JSON.stringify(body);
  if(form.commandSignature!==signature){form.commandSignature=signature;form.commandId=crypto.randomUUID();}
  try {
    const result=await api(path,{...body,command_id:form.commandId});
    await refreshMeta();await render();
    if($('#action-dialog').open)$('#action-dialog').close();
    await openShipment(result.shipment.id);toast('Saved to the test register. History retained.');
  } catch(e){error.textContent=e.message;button.disabled=false;}
}
function newJob() {
  $('#action-dialog').classList.add('wide');
  $('#action-content').innerHTML=`<span class="eyebrow">OWNER ENTRY / TEST REGISTER</span><h2 id="action-title">Create shipment</h2><p>Choose a client and BL. Each job gets its own internal ID. No external messages will be sent.</p><form id="job-create"><div class="form-grid">${selectField('client_id','Client',state.client||String(state.clients[0]?.id),state.clients.map(c=>[String(c.id),c.name]))}${inputField('bl','Bill of Lading','','text','required maxlength="160"')}${inputField('description','Cargo description')}${inputField('container_count','Starting container total','','number','min="1" max="100000" step="1"')}${inputField('import_officer','Import Officer','Owner')}${inputField('field_agent','Field Agent')}${inputField('liner','Shipping line')}${inputField('terminal','Terminal')}${inputField('delivery_location','Delivery location','','text','maxlength="500" placeholder="Client warehouse / delivery address"')}${inputField('eta','ETA','','date')}</div>${commandFooter('Create shipment')}<button type="button" class="button secondary" data-close-action>Cancel</button></form>`;
  $('#action-dialog').showModal();
  $('#job-create').addEventListener('submit',e=>{
    e.preventDefault();const f=e.currentTarget;
    const changes=Object.fromEntries(['bl','description','import_officer','field_agent','liner','terminal','delivery_location'].map(k=>[k,formValue(f,k)]));
    changes.container_count=formValue(f,'container_count')?Number(formValue(f,'container_count')):null;
    changes.dates={eta:formValue(f,'eta')||null};
    saveCommand(f,'/api/shipments',{client_id:Number(formValue(f,'client_id')),changes,...commonCommand(f)});
  });
}
// Owner has deferred these Update job controls; retain them for re-enabling later.
const showWarehouseBalance = false;
function warehouseBalanceFields(r) {
  if(!showWarehouseBalance)return '';
  const superseded=new Set(r.movements.filter(e=>e.supersedes).map(e=>e.supersedes));
  const arrivals=r.movements.filter(e=>e.kind==='warehouse'&&!superseded.has(e.id));
  return `<fieldset class="warehouse-balance"><legend>Warehouse delivery balance</legend><p class="detail-note">Pending warehouse = starting total − recorded warehouse arrivals. Enter the remaining count here; quantity changes are saved as dated arrivals or corrections. Gate-out stays separate.</p><div class="form-grid">${inputField('balance.pending','Pending warehouse',r.pending_count,'number','min="0" max="100000" step="1" placeholder="Not reconciled"')}${inputField('balance.date','Actual warehouse arrival date','','date')}${selectField('balance.event','Warehouse event to correct (optional)','',[['','New arrival / no correction'],...arrivals.map(e=>[e.id,`${e.quantity} containers · ${e.date} · ${e.id.slice(0,8)}`])])}</div><p class="detail-note">Supply an actual arrival date when reducing pending. To increase pending, select the earlier arrival being corrected. Leave pending blank to keep it unknown on an unreconciled job.</p><label class="checkbox-label"><input name="balance.duplicate" type="checkbox"> This is a separate arrival if its date and quantity match an existing event</label><p class="detail-note">Imported jobs need the quantity-reconciliation confirmation below. If release or gate-out evidence is missing, use an exception reason only for a delivery that actually occurred.</p></fieldset><label class="checkbox-label"><input name="reconciled" type="checkbox" ${r.operation.reconciled?'checked':''}> I confirm the starting total and that recorded warehouse quantities include all arrivals I am reporting. Source dates alone do not establish delivered counts.</label>`;
}
function bindWarehouseBalance(r) {
  const form=$('#job-edit');if(!form)return;
  const pending=form.elements.namedItem('balance.pending');if(!pending)return;
  pending.addEventListener('input',()=>{form.balanceTouched=true;});
  form.elements.namedItem('container_count').addEventListener('input',()=>{
    if(!form.balanceTouched&&r.pending_count!==null){
      const total=formValue(form,'container_count');
      pending.value=total?Number(total)-r.delivered_count:'';
    }
  });
  form.elements.namedItem('balance.event').addEventListener('change',e=>{
    const old=r.movements.find(m=>m.id===e.target.value);
    form.elements.namedItem('balance.date').value=old?.date||'';
  });
}
function editJob(r) {
  const o=r.operation;
  return `<form id="job-edit">${notice('Dates are owner-reported facts. Imported raw values remain unchanged. Gate-out and warehouse dates are entered as count-based movements.')}<div class="form-grid">${['bl','description','liner','terminal','import_officer','field_agent','sgd','container_size','delivery_location'].map(k=>inputField(k,({sgd:'C Number / SGD / SDG',field_agent:'Field Agent',delivery_location:'Delivery location',import_officer:'Import Officer',bl:'Bill of Lading'})[k]||k.replaceAll('_',' '),o[k])).join('')}${inputField('container_count','Starting container total',o.container_count,'number','min="1" max="100000" step="1"')}</div>${warehouseBalanceFields(r)}<label class="checkbox-label"><input name="awaiting_duty_receipt" type="checkbox" ${o.awaiting_duty_receipt?'checked':''}> Final assessment received; awaiting duty receipt</label><h3>Documents & milestones</h3><div class="form-grid">${Object.entries(opFields).filter(([k])=>!['gate_out','warehouse'].includes(k)).map(([k,l])=>inputField('dates.'+k,l,o.dates[k],'date')).join('')}</div><h3>Release coverage</h3><p class="detail-note">Confirm cumulative container counts for this job, with the corresponding release dates above. Counts are an owner reconciliation, not individual container identification.</p><div class="form-grid">${['do','tdo','customs_release'].map(k=>inputField('coverage.'+k,fields[k]+' · containers covered',o.release_coverage?.[k],'number','min="1" max="100000" step="1"')).join('')}</div><h3>Rotation number</h3><div class="form-grid">${selectField('rotation_status','Status',o.rotation.status,[['unknown','Unknown'],['not_requested','Nil · not requested'],['gotten','Gotten']])}${inputField('rotation_number','Actual number',o.rotation.number)}</div><h3>Administrative closure</h3><p class="detail-note">Not applicable requires a reason. Refund settlement is not a universal completion gate.</p>${Object.entries(o.closure).map(([k,v])=>`<fieldset><legend>${k==='empty_returns'?'Empty-container returns':'Shipping-line final invoice'}</legend><div class="form-grid">${selectField('closure.'+k+'.applicability','Applicability',v.applicability,applicabilityOptions)}${inputField('closure.'+k+'.date','Completed / received date',v.date,'date')}${inputField('closure.'+k+'.reason','Applicability reason',v.reason)}</div></fieldset>`).join('')}<label class="checkbox-label"><input name="completed" type="checkbox" ${o.completed?'checked':''}> Mark Completed (backend checks delivery, ECD and applicable closure requirements)</label>${commandFooter()}</form>`;
}
function invoiceForm(r) {
  return `<form id="invoice-edit">${notice('Nil means not requested. Unknown, request, receipt and reported payment are separate facts. Rating is the coverage-through date, not the payment date. No rating-expiry automation is active.')}<p class="detail-note">The separate request and receipt fields allow pending invoices to stay visible while the final status terminology is being agreed.</p>${Object.entries(r.operation.invoices).map(([k,v])=>`<fieldset><legend>${({shipping:'Statutory shipping invoice',additional:'Additional shipping invoice',terminal:'Terminal invoice'})[k]}</legend><div class="form-grid">${selectField(k+'.request','Request state',v.request,requestOptions)}${inputField(k+'.received','Invoice received date',v.received,'date')}${selectField(k+'.payment','Reported payment',v.payment,[['unknown','Unknown'],['not_paid','Not paid'],['paid','Paid · owner reported']])}${inputField(k+'.payment_date','Payment date',v.payment_date,'date')}${inputField(k+'.rated_through','Rated through',v.rated_through,'date')}${selectField(k+'.coverage','Invoice coverage',v.coverage,[[k,k==='additional'?'Additional shipping':k==='shipping'?'Shipping':'Terminal'],...(k==='additional'?[]:[['combined','Combined shipping + terminal']])])}${selectField(k+'.applicability','Applicability',v.applicability,applicabilityOptions)}${inputField(k+'.reason','Applicability reason',v.reason)}</div></fieldset>`).join('')}${commandFooter('Save invoice facts',false)}</form>`;
}
function movementForm(r) {
  const superseded=new Set(r.movements.filter(e=>e.supersedes).map(e=>e.supersedes));
  return `${notice('Gate-out requires DO, TDO and Customs release covering the quantity. Warehouse arrival is separate. Correct an event by appending a replacement; use zero only to cancel a selected event.')}<div class="movement-summary"><strong>${r.gate_out_count??'—'} gated out</strong><strong>${r.delivered_count??'—'} at warehouse</strong><strong>${r.pending_count??'—'} pending</strong></div><form id="movement-add"><div class="form-grid">${selectField('kind','Movement','gate_out',[['gate_out','Gate-out'],['warehouse','Warehouse / factory arrival']])}${inputField('date','Actual movement date','','date','required')}${inputField('quantity','Container count','','number','required min="0" max="100000" step="1"')}${selectField('supersedes','New event or correction','',[['','New movement'],...r.movements.filter(e=>!superseded.has(e.id)).map(e=>[e.id,`${e.kind==='gate_out'?'Gate-out':'Warehouse'} · ${e.quantity} · ${e.date} · ${e.id.slice(0,6)}`])])}</div><label class="checkbox-label"><input name="confirm_duplicate" type="checkbox"> Confirm a separate load if count, date and type match an existing event</label>${commandFooter('Record movement')}</form><h3>Movement history</h3>${r.movements.map(e=>`<div class="movement-entry ${superseded.has(e.id)?'superseded':''}"><strong>${e.kind==='gate_out'?'Gate-out':'Warehouse'} · ${e.quantity} containers · ${date(e.date)}</strong><small>${esc(e.id.slice(0,8))}${superseded.has(e.id)?' · superseded':''}${e.supersedes?' · correction of '+esc(e.supersedes.slice(0,8)):''}</small>${e.exception_reason?`<p>Reported exception: ${esc(e.exception_reason)}</p>`:''}</div>`).join('')||'<p class="detail-note">No movement events entered. Blank history does not prove no physical movement occurred.</p>'}`;
}
const teamNames={import_officer:'Import Officer',field_agent:'Field Agent',accounts:'Accounts',qac:'QAC',regulatory:'Regulatory',unassigned:'Unassigned'};
const queueNames={my_next:'My next actions',awaiting_response:'Awaiting responses',clearing_blockers:'Clearing blockers',delivery:'Delivery progress',closure:'Closure'};
const statusNames={open:'Open',in_progress:'In progress',awaiting_response:'Awaiting response',resolved:'Resolved'};
const rolePerson=(r,team)=>({import_officer:r.import_officer,field_agent:r.field_agent})[team]||'';
function actionMarkup(a,button=false) {
  return `<${button?'button':'article'} class="action-item ${button?'action-button':''}" ${button?`data-shipment="${a.shipment_id}" data-open-tab="${a.kind==='coordination'?'coordination':'followups'}"`:''}><div class="action-topline"><span class="badge ${a.status==='awaiting_response'?'preview':''}">${esc(statusNames[a.status])}${a.historical?' · historical':''}</span><span class="team-tag">${esc(a.team_label||teamNames[a.team])}</span></div><h3>${esc(a.title||a.next_action)}</h3>${a.title?`<p><strong>${a.status==='resolved'?'Recorded action:':'Next:'}</strong> ${esc(a.next_action)}</p>`:''}${a.client_name?`<p>${esc(a.client_name)} · ${esc(a.bl)} · ${esc(a.job_id)}</p>`:''}<p><strong>Responsible:</strong> ${esc(a.responsible)} · <strong>Reminder to:</strong> Owner</p>${a.import_officer?`<p>Import Officer: ${esc(a.import_officer)} · Field Agent: ${esc(a.field_agent||'Unassigned')}</p>`:''}${a.authority?`<p>Authority: ${esc(a.authority)}</p>`:''}${a.blocker?`<p><strong>Blocker:</strong> ${esc(a.blocker)}</p>`:''}<p>Source: ${esc(a.source||'Not supplied')}${a.as_of?' · as of '+date(a.as_of):''}</p><p>Last recorded action: ${a.last_action_at?esc(new Date(a.last_action_at*1000).toLocaleString('en-GB',{timeZone:'Africa/Lagos'})):'Not recorded'}</p>${a.assignment_review?'<p class="assignment-review">Earlier saved assignment: confirm its responsible team.</p>':''}${a.blocks_step?`<p class="hold-label">Owner-recorded hold: ${esc({tdo:'TDO',gate_out:'Gate-out',warehouse:'Warehouse arrival',completion:'Completion'}[a.blocks_step])}</p>`:''}</${button?'button':'article'}>`;
}
function deskCards(counts,compact=false) {
  return `<div class="${compact?'desk-overview':'desk-queues'}">${Object.entries(queueNames).map(([key,label])=>`<button class="desk-card ${!compact&&state.deskQueue===key?'selected':''}" data-desk-queue="${key}"><span>${label}</span><strong>${number(counts?.[key])}</strong>${icon('arrow')}</button>`).join('')}</div>`;
}
function followupForm(r) {
  const calculated=r.actions.filter(a=>a.kind==='calculated');
  const options=[...calculated.filter(a=>a.key!=='reported_blocker').map(a=>[a.key,a.next_action]),['reported_blocker','Reported blocker / custom next action']];
  return `${notice('You coordinate the job as Import Officer. Assign the next action to a team/person; reminders remain addressed to the owner. No messages are sent.')}<div class="action-items">${calculated.map(a=>actionMarkup(a)).join('')||'<p class="detail-note">No current calculated follow-ups.</p>'}</div><form id="followup-edit"><div class="form-grid">${selectField('key','Action to update',options[0][0],options)}${selectField('team','Responsible team','import_officer',Object.entries(teamNames))}${selectField('status','Action status','awaiting_response',Object.entries(statusNames).filter(([k])=>k!=='resolved'))}${inputField('responsible','Responsible person (optional)')}${inputField('blocker','Reported blocker')}${inputField('next_action','Next action (optional override)')}${inputField('source','Supporting source')}</div><p id="assignment-hint" class="detail-note"></p><p class="detail-note">Document and payment actions are fulfilled by their underlying records. Sending a request keeps the item open as awaiting response.</p>${commandFooter('Record follow-up',false)}</form>`;
}
function coordinationForm(r) {
  const items=Object.values(r.operation.coordination);
  return `${notice('Record team tasks and regulatory issues manually. No authority requirements are inferred. An optional process hold applies only when you explicitly record it.')}<div class="coordination-list">${items.map(i=>`<article class="coordination-row"><div><span class="badge">${esc(statusNames[i.status])}</span><span class="team-tag">${esc(teamNames[i.team])}</span><h3>${esc(i.title)}</h3><p>${esc(i.next_action)}</p><p>${esc(i.responsible||rolePerson(r,i.team)||'Unassigned')}${i.authority?' · '+esc(i.authority):''}</p>${i.blocker?`<p>${i.status==='resolved'?'Earlier blocker':'Blocker'}: ${esc(i.blocker)}</p>`:''}<p>Source: ${esc(i.source)}</p>${i.blocks_step?`<p class="hold-label">Process hold: ${esc({tdo:'TDO',gate_out:'Gate-out',warehouse:'Warehouse arrival',completion:'Completion'}[i.blocks_step])}</p>`:''}${i.resolution_date?`<p>${i.status==='resolved'?'Resolution':'Last resolution'}: ${date(i.resolution_date)} · ${esc(i.resolution_note)}</p>`:''}</div><button type="button" class="button secondary" data-edit-coordination="${i.id}">Edit item</button></article>`).join('')||'<p class="detail-note">No manual coordination items yet.</p>'}</div><h3 id="coordination-heading">Add coordination item</h3><form id="coordination-edit"><input name="item_id" type="hidden"><div class="form-grid">${inputField('title','Issue / task title','','text','required maxlength="500"')}${selectField('category','Work area','clearing',[['clearing','Clearing'],['delivery','Delivery'],['closure','Closure'],['regulatory','Regulatory']])}${selectField('team','Responsible team','import_officer',Object.entries(teamNames))}${inputField('responsible','Responsible person (optional)')}${inputField('authority','Regulatory authority (optional)')}${selectField('status','Item status','open',Object.entries(statusNames))}${inputField('blocker','Reported blocker','','text','maxlength="1000"')}${inputField('next_action','Next action','','text','required maxlength="1000"')}${inputField('source','Supporting source','','text','required maxlength="500"')}${selectField('blocks_step','Explicit process hold','',[['','No process hold'],['tdo','TDO'],['gate_out','Gate-out'],['warehouse','Warehouse arrival'],['completion','Completion']])}${inputField('resolution_note','Resolution note (required when resolved)','','text','maxlength="1000"')}${inputField('resolution_date','Resolution date (required when resolved)','','date')}</div><p class="detail-note">Responsible person may be left blank to use the job’s Import Officer / Field Agent for that team. Other teams remain unassigned until you name someone. Reminder recipient: Owner.</p>${commandFooter('Save coordination item',false)}<button type="button" class="button secondary" id="new-coordination">Start a new item</button></form>`;
}
function bindFollowup(r) {
  const form=$('#followup-edit');if(!form)return;
  const hint=()=>$('#assignment-hint').textContent='Job assignment for this team: '+(rolePerson(r,formValue(form,'team'))||'Unassigned')+'. Reminder recipient: Owner.';
  const populate=()=>{
    const saved=r.operation.followups[formValue(form,'key')]||{};
    for(const key of ['team','status','responsible','blocker','next_action','source'])form.elements.namedItem(key).value=saved[key]??({team:'import_officer',status:'awaiting_response'})[key]??'';
    hint();
  };
  form.elements.namedItem('key').addEventListener('change',populate);
  form.elements.namedItem('team').addEventListener('change',hint);
  populate();
}
function bindCoordination(r) {
  const form=$('#coordination-edit');if(!form)return;
  const keys=['title','category','team','responsible','authority','status','blocker','next_action','source','blocks_step','resolution_note','resolution_date'];
  const fill=id=>{
    const item=r.operation.coordination[id]||{};
    form.reset();form.elements.namedItem('item_id').value=id||'';
    for(const key of keys)form.elements.namedItem(key).value=item[key]??({category:'clearing',team:'import_officer',status:'open'})[key]??'';
    $('#coordination-heading').textContent=id?'Update coordination item':'Add coordination item';
    form.commandSignature=null;
  };
  $$('[data-edit-coordination]').forEach(button=>button.addEventListener('click',()=>{fill(button.dataset.editCoordination);$('#coordination-heading').scrollIntoView({block:'start',behavior:'smooth'});}));
  $('#new-coordination').addEventListener('click',()=>fill(''));
  form.addEventListener('submit',event=>{
    event.preventDefault();const f=event.currentTarget;
    const item=Object.fromEntries(keys.map(k=>[k,formValue(f,k)||(k==='resolution_date'?null:'')]));
    saveCommand(f,`/api/shipments/${r.id}/coordination`,{revision:r.revision,item_id:formValue(f,'item_id')||null,item,...commonCommand(f)});
  });
}
function renderDetail(tab='milestones') {
  const r=state.detail,d=r.dates,editable=Boolean(r.id),o=r.operation;
  const available=editable?[['milestones','Summary'],['edit','Update job'],['invoices','Invoices'],['movements','Movements'],['followups','Follow-ups'],['coordination','Team coordination'],['source','Source & history']]:[['milestones','Milestones'],['source','Original source']];
  $('#detail-content').innerHTML=`<header class="detail-top"><div class="detail-topline"><span>${esc(r.client_name)} / ${esc(r.job_id)}</span><button class="icon-button" data-close-detail aria-label="Close shipment details">${icon('close')}</button></div><h2 id="detail-title">${esc(r.bl)}</h2><p>${esc(r.description)}</p><div class="job-officers"><span>Import Officer(s)</span><strong>${esc(r.import_officer||(editable?'Unassigned':'Assigned after import'))}</strong></div><div class="detail-badges">${pill(r.state||r.proposed_state)}<span class="badge preview">${esc(r.review_status||'Historical proposal')}</span><span class="badge">${r.source_row?'CSV row '+r.source_row:'Manual entry'}</span></div></header><div class="detail-tabs">${available.map(([key,label])=>`<button class="detail-tab ${tab===key?'active':''}" data-detail-tab="${key}">${label}</button>`).join('')}</div><div class="detail-body"></div>`;
  const body=$('.detail-body',$('#detail-content'));
  if(tab==='edit'&&editable)body.innerHTML=editJob(r);
  else if(tab==='invoices'&&editable)body.innerHTML=invoiceForm(r);
  else if(tab==='movements'&&editable)body.innerHTML=movementForm(r);
  else if(tab==='followups'&&editable)body.innerHTML=followupForm(r);
  else if(tab==='coordination'&&editable)body.innerHTML=coordinationForm(r);
  else if(tab==='source') {
    const source=r.source_snapshot||r;
    body.innerHTML=`<section class="detail-section"><h3>Original source</h3>${r.batch_id?`<p class="source-meta">File: ${esc(r.filename)}<br>Section: ${esc(source.section)}<br>Physical CSV row: ${r.source_row}<br>Reporting cut-off: ${r.report_date?date(r.report_date):'Unknown'}<br>Import batch: ${esc(r.batch_id)}</p>${notice('Original values remain unchanged beneath owner updates.')}<table class="raw-table"><tbody>${source.raw.map((v,i)=>`<tr><td>${esc(source.source_headers?(source.source_headers[i]||'Unnamed column '+(i+1)):(sourceHeaders[i]||'Column '+(i+1)))}</td><td>${v?esc(v):'<span class="muted">Empty cell</span>'}</td></tr>`).join('')}</tbody></table>`:'<p class="detail-note">Created manually by the owner. No CSV source is attached.</p>'}</section><section class="detail-section"><h3>Application history</h3>${(r.history||[]).map(e=>`<details class="history-entry"><summary>${esc(e.action.replaceAll('_',' '))} · ${esc(new Date(e.at*1000).toLocaleString('en-GB',{timeZone:'Africa/Lagos'}))} · ${esc(e.actor)}</summary>${e.detail?.reason?`<p>Reason: ${esc(e.detail.reason)}</p>`:''}<pre>${esc(JSON.stringify(e.detail||{},null,2))}</pre></details>`).join('')||'<p class="detail-note">No recorded changes.</p>'}</section>`;
  } else {
    body.innerHTML=`${notice(esc(r.state_note),!o?.reconciled)}<div class="detail-facts">${[['Terminal',r.terminal],['Shipping line',r.liner],['Containers',r.container_count],['Pending warehouse',r.pending_count],['Delivery location',r.delivery_location],['Field Agent',r.field_agent??r.handler],['Reminder recipient','Owner'],['C Number / SGD',r.sgd]].map(([l,v])=>`<div class="fact"><span>${l}</span><strong>${esc(v??'Not established')||'Not recorded'}</strong></div>`).join('')}</div>${r.assessment?.draft_requirements_cleared?notice('Client approval follow-up cleared: final assessment received date and C Number are recorded. No approval date or approver was inferred.'):''}<section class="detail-section"><h3>Documents & milestones</h3><div class="milestone-grid">${Object.entries(opFields).map(([k,l])=>`<div class="milestone ${d[k]?'recorded':''}"><span class="milestone-label"><i class="milestone-dot"></i>${l}</span><span class="milestone-value ${!d[k]?'missing':''}">${d[k]?date(d[k]):'Not recorded / review'}</span></div>`).join('')}</div><p class="detail-note">Client approval remains part of preparing the final assessment; approval details are not recorded here for now. Document dates do not independently verify documents or payment.</p></section>${editable?`<section class="detail-section"><h3>Next actions</h3>${r.actions.filter(a=>a.status!=='resolved').map(a=>`<div class="finding">${icon('clock')}<div><p>${esc(a.next_action)}</p><small>${esc(statusNames[a.status])} · ${esc(a.team_label)} / ${esc(a.responsible)} · ${esc(a.source)} · Reminder to: Owner</small></div></div>`).join('')||'<p class="detail-note">No calculated follow-ups.</p>'}</section><section class="detail-section"><h3>Completion checklist</h3>${r.closure_missing.length?`<p class="detail-note">Still needed: ${r.closure_missing.map(esc).join('; ')}.</p>`:notice('Closure requirements recorded. Use Update job to confirm Completed.')}</section>`:''}${pendingReport(r)}<section class="detail-section"><h3>Original comment</h3><div class="comment-box">${esc(r.comments||'No source comment.')}</div></section><section class="detail-section"><h3>Review findings</h3>${r.issues.map(i=>`<div class="finding">${icon(i.severity==='info'?'info':'warning')}<div><p>${esc(i.message)}</p><small>${esc(i.source||'Original import')} · ${esc(i.field||'Record')}</small></div></div>`).join('')||'<p class="detail-note">No automated findings. Owner entries are not independent verification.</p>'}</section>`;
  }
  bindWarehouseBalance(r);
  $('#job-edit')?.addEventListener('submit',e=>{
    e.preventDefault();const f=e.currentTarget;
    const changes=Object.fromEntries(['bl','description','liner','terminal','import_officer','field_agent','sgd','container_size','delivery_location'].map(k=>[k,formValue(f,k)]));
    changes.dates=dateValues(f);changes.container_count=formValue(f,'container_count')?Number(formValue(f,'container_count')):null;
    // Omit hidden controls so ordinary edits preserve the saved reconciliation status.
    for(const k of ['reconciled','awaiting_duty_receipt','completed']){
      const control=f.elements.namedItem(k);if(control)changes[k]=control.checked;
    }
    changes.release_coverage=Object.fromEntries(['do','tdo','customs_release'].map(k=>[k,formValue(f,'coverage.'+k)?Number(formValue(f,'coverage.'+k)):null]));
    changes.rotation={status:formValue(f,'rotation_status'),number:formValue(f,'rotation_number')};
    changes.closure=Object.fromEntries(['empty_returns','shipping_final'].map(k=>[k,{applicability:formValue(f,'closure.'+k+'.applicability'),date:formValue(f,'closure.'+k+'.date')||null,reason:formValue(f,'closure.'+k+'.reason')}]));
    const payload={revision:r.revision,changes,...commonCommand(f)};
    const pending=formValue(f,'balance.pending'),event=formValue(f,'balance.event'),arrivalDate=formValue(f,'balance.date');
    if(pending===''&&(event||arrivalDate)){$('.command-error',f).textContent='Enter Pending warehouse before recording an arrival or correction.';return;}
    if(pending!==''&&(f.balanceTouched||event||arrivalDate))payload.warehouse_balance={pending_count:Number(pending),date:arrivalDate||null,supersedes:event||null,confirm_duplicate:f.elements.namedItem('balance.duplicate').checked};
    saveCommand(f,`/api/shipments/${r.id}/update`,payload);
  });
  $('#invoice-edit')?.addEventListener('submit',e=>{
    e.preventDefault();const f=e.currentTarget;
    const invoices=Object.fromEntries(Object.entries(o.invoices).map(([k,v])=>[k,Object.fromEntries(Object.keys(v).map(field=>[field,formValue(f,k+'.'+field)||(['received','payment_date','rated_through'].includes(field)?null:'')]))]));
    saveCommand(f,`/api/shipments/${r.id}/update`,{revision:r.revision,changes:{invoices},...commonCommand(f)});
  });
  $('#movement-add')?.addEventListener('submit',e=>{
    e.preventDefault();const f=e.currentTarget;
    saveCommand(f,`/api/shipments/${r.id}/movements`,{revision:r.revision,kind:formValue(f,'kind'),date:formValue(f,'date'),quantity:Number(formValue(f,'quantity')),supersedes:formValue(f,'supersedes')||null,confirm_duplicate:f.elements.namedItem('confirm_duplicate').checked,...commonCommand(f)});
  });
  bindFollowup(r);bindCoordination(r);
  $('#followup-edit')?.addEventListener('submit',e=>{
    e.preventDefault();const f=e.currentTarget;
    saveCommand(f,`/api/shipments/${r.id}/followups`,{revision:r.revision,...Object.fromEntries(['key','team','status','responsible','blocker','next_action','source'].map(k=>[k,formValue(f,k)])),...commonCommand(f)});
  });
}
async function renderActions(version) {
  const q=new URLSearchParams({queue:state.deskQueue,team:state.deskTeam,status:state.deskStatus});if(state.client)q.set('client_id',state.client);
  const result=await api('/api/actions?'+q);if(version!==state.version)return;
  $('#main').innerHTML=heading()+tabs()+notice('Your coordination desk across all teams. Responsibility is separate from reminder delivery: reminders come to the owner, and sending remains disabled. Historical dates use their report cut-off.')+deskCards(result.queue_counts)+`<section class="panel"><div class="panel-header"><div class="panel-title">${esc(queueNames[state.deskQueue]||'All coordination actions')} <span class="count-tag">${result.actions.length}</span></div><button class="text-link" data-desk-queue="all">Show all actions</button></div><div class="desk-filters">${selectField('desk-team','Responsible team',state.deskTeam,[['','All teams'],...Object.entries(result.teams)])}${selectField('desk-status','Status',state.deskStatus,[['','All active items'],...Object.entries(result.statuses)])}</div><div class="action-items">${result.actions.map(a=>actionMarkup(a,true)).join('')||empty('No items in this queue','Change the team, status or queue filter, or add a coordination item from a shipment.','')}</div></section>`;
  $('#edit-desk-team').addEventListener('change',async e=>{state.deskTeam=e.target.value;await render();});
  $('#edit-desk-status').addEventListener('change',async e=>{state.deskStatus=e.target.value;state.deskQueue='all';await render();});
}

function addClient() {
  $('#action-content').innerHTML=`<span class="eyebrow">CLIENT REGISTER</span><h2 id="action-title">Add a client</h2><p>Create the client now. Its source mapping can be reviewed when the report is available.</p><form id="client-form"><div class="field"><label for="client-name">Client name</label><input id="client-name" minlength="2" maxlength="60" required placeholder="e.g. Nestlé"></div><p id="client-error" class="form-error" role="alert"></p><div class="dialog-actions"><button type="button" class="button secondary" data-close-action>Cancel</button><button type="submit" class="button primary">Add client</button></div></form>`;
  $('#action-dialog').showModal();
  $('#client-form').addEventListener('submit',async event=>{
    event.preventDefault();const button=$('button[type=submit]',event.currentTarget);button.disabled=true;
    try{await api('/api/clients',{name:$('#client-name').value});$('#action-dialog').close();await refreshMeta();await render();toast('Client added. No shipment data was created.');}
    catch(error){$('#client-error').textContent=error.message;button.disabled=false;}
  });
}
function notificationsInfo() {
  $('#action-content').innerHTML=`<span class="eyebrow">WORKSPACE STATUS</span><h2 id="action-title">Reminders come next.</h2><p>This slice supports test imports and shipment visibility. Hermes, Telegram and scheduled reminders are not connected.</p><p class="detail-note">The planned owner schedule is 08:00 and 16:00 Africa/Lagos. No outbound notifications are active.</p><div class="dialog-actions"><button class="button primary" data-close-action>Understood</button></div>`;$('#action-dialog').showModal();
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('button');const row=event.target.closest('tr[data-shipment],tr[data-preview-row]');
  try{
    if(button?.hasAttribute('data-desk-queue')){state.deskQueue=button.dataset.deskQueue;state.deskStatus='';await navigate('actions');return;}
    if(button?.dataset.page){await navigate(button.dataset.page);return;}
    if(button?.dataset.go){await navigate(button.dataset.go);return;}
    if(button?.hasAttribute('data-client')){state.client=button.dataset.client;state.pageNumber=1;state.filter='';state.search='';if(state.page==='imports')state.page='shipments';$('#sidebar').classList.remove('open');syncSidebar();await render();return;}
    if(button?.dataset.state){state.filter=state.filter===button.dataset.state?'':button.dataset.state;state.pageNumber=1;await render();return;}
    if(button?.hasAttribute('data-issues')){state.issues=button.dataset.issues==='1';state.pageNumber=1;await loadTable();return;}
    if(button?.dataset.pageTurn){state.pageNumber+=Number(button.dataset.pageTurn);await loadTable();return;}
    if(button?.dataset.source){await preview({source_id:button.dataset.source});return;}
    if(button?.dataset.batch){await openBatch(button.dataset.batch);return;}
    if(button?.hasAttribute('data-preview-issues')){state.previewIssues=button.dataset.previewIssues==='1';state.previewPage=1;renderPreview();return;}
    if(button?.dataset.previewPage){state.previewPage+=Number(button.dataset.previewPage);renderPreview();return;}
    const shipment=button?.dataset.shipment||row?.dataset.shipment;if(shipment){await openShipment(shipment);if(button?.dataset.openTab)renderDetail(button.dataset.openTab);return;}
    const previewRow=button?.dataset.previewRow||row?.dataset.previewRow;if(previewRow){openPreviewRow(previewRow);return;}
    if(button?.dataset.detailTab){renderDetail(button.dataset.detailTab);return;}
    if(button?.hasAttribute('data-close-detail')){$('#detail-dialog').close();return;}
    if(button?.hasAttribute('data-close-action')){$('#action-dialog').close();return;}
    if(button?.id==='new-job'){newJob();return;}
    if(button?.id==='apply-import'){confirmApply();return;}
    if(button?.id==='retry-load'){await render();return;}
  }catch(error){toast(error.message);}
});
document.addEventListener('input',event=>{
  if(event.target.id==='shipment-search'){
    state.search=event.target.value;state.pageNumber=1;clearTimeout(searchTimer);
    const version=++state.version;
    searchTimer=setTimeout(async()=>{try{const position=event.target.selectionStart;await loadTable(version);const input=$('#shipment-search');if(input&&version===state.version){input.focus();input.setSelectionRange(position,position);}}catch(error){toast(error.message);}},300);
  }
});
$('#action-dialog').addEventListener('close',()=>$('#action-dialog').classList.remove('wide'));
$('#add-client').addEventListener('click',addClient);
$('#mobile-menu').addEventListener('click',()=>{$('#sidebar').classList.toggle('open');syncSidebar();});
matchMedia('(max-width:680px)').addEventListener('change',syncSidebar);
$('#notification-info').addEventListener('click',notificationsInfo);
$('#logout').addEventListener('click',async()=>{try{await api('/api/auth/logout',{});state.csrf=null;state.batch=null;await showAuth();}catch(error){toast(error.message);}});
$('#detail-dialog').addEventListener('click',event=>{if(event.target===$('#detail-dialog'))$('#detail-dialog').close();});
paintIcons();syncSidebar();
showAuth().catch(error=>{$('#boot').innerHTML=`<span class="brand-symbol">L</span><p>Workspace unavailable</p><p>${esc(error.message)}</p><button class="button secondary" id="boot-retry">Try again</button>`;$('#boot-retry').onclick=()=>location.reload();});
