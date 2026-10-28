'use strict';

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clone = (v) => JSON.parse(JSON.stringify(v));
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const numeric = (v, places = 2) => v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? '—' : Number(v).toLocaleString('en-US', {minimumFractionDigits:places,maximumFractionDigits:places});
const compact = (v, max = 2) => v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? '—' : Number(v).toLocaleString('en-US', {maximumFractionDigits:max});
const money = (v, cur='USD', places=2) => v === null || v === undefined || v === '' ? '待补齐' : `${esc(cur)} ${numeric(v,places)}`;
const labels = {air:'空运',fcl:'海运整柜',origin:'起运地费用',freight:'主运费',destination:'目的地费用',estimated:'预算已齐',simulated:'模拟预估',partial:'费用待补充',invalid:'资料需补充',historical:'历史费率参考',not_applicable:'暂无适用费率'};
const basisLabels = {pallet:'每板',carton:'每箱',origin_truck:'起运车次',destination_truck:'派送车次',shipment:'每票',container:'每柜',chargeable_kg:'计费kg',gross_kg:'毛重kg',volume_m3:'m³'};
const feeStateLabels = {priced:'已计价',included:'已含',excluded:'不计入',not_applicable:'不适用',missing:'待询价',pending:'待询价'};

const state = {catalog:null,result:null,lastRequest:null,snapshot:null,parentId:null,readonly:false,dirty:false,busy:false,selectedQuantity:null,selectedSupplier:null,selectedMode:'air',detailTab:'fees',view:'quick',materialTab:'products',sources:[],ratePlanId:null,requestGeneration:0};
let toastTimer;

async function api(path, options={}) {
  if(window.FreightWorkspace?.enabled)return window.FreightWorkspace.request(path,options);
  const response = await fetch(path, {cache:'no-store',...options,headers:{'Content-Type':'application/json',...options.headers}});
  const ct = response.headers.get('content-type') || '';
  const body = ct.includes('json') ? await response.json() : await response.text();
  if (!response.ok) {
    const value = typeof body === 'object' ? body.error || body.message || body.detail : body;
    throw new Error(typeof value === 'string' ? value : JSON.stringify(value || '请求未能完成'));
  }
  return body;
}
const post = (path,body) => api(path,{method:'POST',body:JSON.stringify(body)});
const currentCatalog = () => state.readonly && state.snapshot?.catalog_snapshot ? state.snapshot.catalog_snapshot : state.catalog;
const rows = (name, cat=currentCatalog()) => Array.isArray(cat?.[name]) ? cat[name] : [];
const find = (name,id,cat=currentCatalog()) => rows(name,cat).find(x => x.id === id);
function toast(message) { clearTimeout(toastTimer);$('toast').textContent=message;$('toast').hidden=false;toastTimer=setTimeout(()=>{$('toast').hidden=true;},4200); }
function globalError(message='') {$('appError').textContent=message;$('appError').hidden=!message;}
function setBusy(value,label='正在计算…') {state.busy=value;$('calculate').disabled=value||state.readonly;$('calculate').innerHTML=value ? `${esc(label)}` : `计算运费${icon('arrow')}`;}

function setOptions(el, entries, selected) {
  el.innerHTML=entries.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('');
  if (entries.some(x=>x.id===selected)) el.value=selected;
}
function refreshPackaging(selected) {
  const entries=rows('packagings').filter(x=>x.product_id===$('product').value);
  setOptions($('packaging'),entries,selected || find('products',$('product').value)?.default_packaging_id);
  updateProductSummary();
}
function updateProductSummary() {
  const p=find('products',$('product').value), box=p?.carton;
  $('productSummary').textContent=p ? `${p.composition || ''}${box ? ` · ${box.units_per_carton}${p.unit||'套'}/箱 · ${box.length_mm}×${box.width_mm}×${box.height_mm} mm` : ''}` : '';
}
function updateEstimationMode() {
  $('estimationModeTag').textContent=$('demoEstimation').checked?'DEMO · 演示估价':'DEMO · 严格匹配';
}
function fillForm(request) {
  const c=currentCatalog();
  setOptions($('product'),rows('products',c),request.product_id);
  refreshPackaging(request.packaging_id);
  setOptions($('origin'),rows('locations',c).filter(x=>x.kind==='origin'),request.origin_id);
  setOptions($('destination'),rows('locations',c).filter(x=>x.kind==='destination'),request.destination_id);
  setOptions($('service'),rows('services',c),request.service_id);
  const supplierList=rows('suppliers',c);
  $('supplier').innerHTML=supplierList.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('')+(supplierList.length>1?'<option value="__all">同时比较全部货代</option>':'');
  $('supplier').value=request.supplier_ids?.length>1?'__all':request.supplier_ids?.[0] || supplierList[0]?.id;
  $('quantities').value=(request.quantities||[1000,3000]).join(', ');
  $('departure').value=request.departure_date||'';
  $('modeAir').checked=request.modes?.includes('air')??true;
  $('modeFcl').checked=request.modes?.includes('fcl')??true;
  $('demoEstimation').checked=request.demo_estimation!==false;
  updateEstimationMode();
  $('bu').value=request.metadata?.bu||'';
  $('reference').value=request.metadata?.reference||'';
  $('notes').value=request.metadata?.note||request.metadata?.notes||'';
  $('quickForm').querySelectorAll('input,select,button').forEach(x=>{x.disabled=state.readonly;});
  $('quickForm').classList.toggle('readonly-form',state.readonly);
  $('catalogVersion').textContent=c?.version||'';
}
function readRequest() {
  const values=$('quantities').value.split(/[,，、;；\s]+/).filter(Boolean);
  if (!values.length || values.some(x=>!/^\d+$/.test(x)||Number(x)<1||!Number.isSafeInteger(Number(x)))) throw new Error('订货数量请填写正整数，多个数量用逗号分隔。');
  if (values.length>8) throw new Error('一次最多比较8档订货数量。');
  const modes=[$('modeAir').checked?'air':null,$('modeFcl').checked?'fcl':null].filter(Boolean);
  if (!modes.length) throw new Error('请至少选择一种运输方式。');
  if (!$('departure').value) throw new Error('请选择计划启运日期。');
  const old=state.lastRequest||state.catalog.default_request||{};
  return {product_id:$('product').value,quantities:[...new Set(values.map(Number))],packaging_id:$('packaging').value,origin_id:$('origin').value,destination_id:$('destination').value,service_id:$('service').value,departure_date:$('departure').value,modes,supplier_ids:$('supplier').value==='__all'?rows('suppliers',state.catalog).map(x=>x.id):[$('supplier').value],fx_id:old.fx_id||rows('fx',state.catalog)[0]?.id,demo_estimation:$('demoEstimation').checked,metadata:{bu:$('bu').value.trim(),reference:$('reference').value.trim(),note:$('notes').value.trim()}};
}
function markDirty() {
  if(state.readonly)return;
  state.requestGeneration++;
  state.dirty=true;
  state.snapshot=null;
  $('formState').textContent='条件已变更，等待重算';
  if(state.result)renderResults();
}

async function calculate() {
  if(state.readonly)return;
  globalError('');
  let request;try{request=readRequest();}catch(e){toast(e.message);return false;}
  const generation=state.requestGeneration;
  setBusy(true);
  try {
    const result=await post('/api/calculate',request);
    if(generation!==state.requestGeneration){toast('条件已变更，请按最新条件重新计算。');return false;}
    state.result=result;state.lastRequest=clone(request);state.snapshot=null;state.dirty=false;
    state.selectedQuantity=request.quantities.includes(state.selectedQuantity)?state.selectedQuantity:request.quantities[0];
    state.selectedSupplier=request.supplier_ids.includes(state.selectedSupplier)?state.selectedSupplier:request.supplier_ids[0];
    if(!request.modes.includes(state.selectedMode))state.selectedMode=request.modes[0];
    $('formState').textContent=(result.results||[]).some(r=>r.estimate?.applied)?'已用模拟参数完成预估':'已按当前条件计算';
    renderResults();
    return true;
  } catch(e) {globalError(e.message);return false;} finally{setBusy(false);}
}

function selectedResult(mode=state.selectedMode,qty=state.selectedQuantity,supplier=state.selectedSupplier) {
  return state.result?.results?.find(x=>x.mode===mode&&Number(x.quantity)===Number(qty)&&x.supplier_id===supplier);
}
function statusLabel(r) {return r ? labels[r.status] || (r.complete?'预算已齐':'费用待补充') : '未选择';}
function priceValue(r,per=false) {return r?.[per?'per_set':'budget_total']??null;}
function messageText(m) {return typeof m==='string'?m:m?.text||m?.message||'';}
function budgetLarge(r) {
  if(!r)return '<span class="currency">USD</span>—';
  const amount=priceValue(r);
  if(amount===null)return `<span class="currency">USD</span><span style="font-size:.6em;letter-spacing:0">${r.status==='partial'?'费用待补齐':r.status==='not_applicable'?'暂无适用费率':'暂不能计价'}</span>`;
  const [a,b]=numeric(amount).split('.');
  return `<span class="currency">USD</span>${a}<span class="decimal">.${b||'00'}</span>`;
}
function transitText(r) {
  const t=r?.transit;
  if(!t)return '时效待确认';
  if(typeof t==='string')return t;
  return t.min!==undefined&&t.max!==undefined?`${t.min}–${t.max} ${t.unit||'自然日'}`:'时效待确认';
}
function budgetCard(mode) {
  const r=selectedResult(mode);
  const title=mode==='air'?'空运':'海运整柜';
  const isPartial=r?.budget_total===null&&r?.known_budget!==null&&r?.known_budget!==undefined;
  return `<article class="budget-card ${mode==='air'?'air':'sea'}-card ${!r?'mode-disabled':''}">
    <div class="mode-heading"><span class="mode-symbol">${icon(mode==='air'?'air':'ship')}</span><div><h3>${title}</h3><small>${mode==='air'?'AIR FREIGHT':'OCEAN · FCL'}</small></div><span class="card-status ${esc(r?.status||'')}">${esc(statusLabel(r))}</span></div>
    <div class="budget-value">${budgetLarge(r)}</div>
    <div class="per-unit">${priceValue(r,true)!==null?`每套 <strong>${numeric(priceValue(r,true),4)}</strong> USD / 套`:(isPartial?`已知部分 ${money(r.known_budget)} · 每套已知 ${numeric(r.known_per_set,4)} USD`:'选择适用费率后显示每套运费')}</div>
    <div class="card-bottom"><span>参考时效 <strong>${esc(transitText(r))}</strong></span><button type="button" class="basis-link" data-action="show-mode" data-mode="${mode}">查看计费依据 →</button></div>
  </article>`;
}
function renderResults() {
  if(!state.result)return;
  const req=state.lastRequest||state.result.request||{};
  const list=state.result.results||[];
  const quantities=req.quantities||[...new Set(list.map(x=>x.quantity))];
  const suppliers=req.supplier_ids||[...new Set(list.map(x=>x.supplier_id))];
  const r=selectedResult('air')||selectedResult('fcl')||list[0];
  const s=r?.shipping||{};
  const route=find('locations',req.destination_id)?.name||r?.route_label||'';
  const service=find('services',req.service_id)?.name||'';
  const supplierControls=suppliers.length>1?`<div class="supplier-toggle">${suppliers.map(id=>`<button data-action="supplier" data-id="${esc(id)}" class="${id===state.selectedSupplier?'active':''}">${esc((find('suppliers',id)?.name||id).replace('演示货代 ','货代 '))}</button>`).join('')}</div>`:'';
  $('resultArea').innerHTML=`${state.dirty?'<div class="dirty-notice">条件已修改。下方为上次结果，重新计算后可保存与导出。</div>':''}
  <div class="section-heading"><div><h2>方案一览</h2><p>${esc(route)} <span> · </span> ${esc(service)} <span> · </span> 预算币 USD <span> · </span> ${req.demo_estimation!==false?'演示估价':'严格匹配'}</p></div><div class="result-controls">${supplierControls}<div class="segmented" aria-label="查看数量">${quantities.map(q=>`<button data-action="quantity" data-qty="${q}" class="${Number(q)===Number(state.selectedQuantity)?'active':''}">${compact(q,0)}套</button>`).join('')}</div></div></div>
  <div class="result-cards">${budgetCard('air')}${budgetCard('fcl')}</div>
  <div class="shipping-strip">${[
    ['出运纸箱',s.carton_count,'箱'],['托盘数量',s.pallet_count,'板'],['交运体积',s.volume_m3,'m³'],['交运毛重',s.gross_kg,'kg'],...(req.modes?.includes('fcl')?[['FCL装载',(selectedResult('fcl')?.shipping||{}).container_count,'× '+((selectedResult('fcl')?.shipping||{}).container_type||'柜')]]:[])
  ].map(([l,v,u])=>`<div class="shipping-stat"><small>${l}</small><strong>${compact(v,2)}</strong><span>${u}</span></div>`).join('')}</div>
  ${renderComparison(quantities,suppliers)}
  <div class="result-detail-tabs"><div class="tabbar">${[['fees','费用明细'],['packaging','包装与装载依据'],['conditions','范围与来源']].map(([key,label])=>`<button data-action="detail-tab" data-tab="${key}" class="${key===state.detailTab?'active':''}">${label}</button>`).join('')}</div><div class="detail-content surface" id="resultDetail"></div></div>
  <div class="result-actions"><div><button class="button secondary" id="saveEstimate" ${state.dirty||state.readonly||state.snapshot?'disabled':''}>${icon('check')}${state.snapshot?'已保存 '+esc(state.snapshot.number):state.parentId?'保存新版本':'保存本次测算'}</button><span class="saving-indicator" id="saveFeedback"></span></div><div class="export-buttons"><button class="button ghost" data-action="export" data-format="pdf" ${state.dirty?'disabled':''}>${icon('down')}测算单 PDF</button><button class="button ghost" data-action="export" data-format="xlsx" ${state.dirty?'disabled':''}>明细 Excel</button><button class="button ghost" data-action="export" data-format="inquiry" ${state.dirty?'disabled':''}>询价资料</button><button class="button ghost" data-action="export" data-format="json" ${state.dirty?'disabled':''}>快照 JSON</button></div></div>
  <p class="result-notes">本页为企业内部预算。预置产品、包装、装载模板、费率与汇率均按模拟条件设定；大货舱位、拆票与实际承运安排需另行确认。</p>`;
  renderDetail();
  $('saveEstimate')?.addEventListener('click',()=>saveSnapshot().catch(e=>toast(e.message)));
  updateSnapshotBanner();
}
function renderComparison(quantities,suppliers) {
  return `<div class="surface comparison-surface"><div class="surface-heading"><h3>数量 × 运输方式</h3><small>同一服务范围 · 原币小计按预算汇率折算</small></div><div class="table-wrap"><table><thead><tr><th>订货数量</th><th>货代方案</th><th class="number mode-col-air">空运总预算 · USD</th><th class="number">每套 · USD</th><th class="number">海运总预算 · USD</th><th class="number">每套 · USD</th></tr></thead><tbody>${quantities.flatMap(q=>suppliers.map(sid=>{const air=selectedResult('air',q,sid),sea=selectedResult('fcl',q,sid);return `<tr><td class="qty-cell">${compact(q,0)}<small>套</small></td><td class="supplier-cell">${esc(find('suppliers',sid)?.name||sid)}</td>${[air,sea].map(x=>`<td class="number total-number">${x?.budget_total!==null&&x?.budget_total!==undefined?`${numeric(x.budget_total)}${x.status==='simulated'?'<span class="tiny-label simulated-cell-label">模拟预估</span>':''}`:`<span class="pill ${x?.status==='partial'?'amber':'neutral'}">${esc(statusLabel(x))}</span>`}</td><td class="number unit-number">${numeric(x?.per_set,4)}</td>`).join('')}</tr>`;})).join('')}</tbody></table></div></div>`;
}
function detailHeader(title) {
  const modes=state.lastRequest?.modes||['air','fcl'];
  return `<div class="surface-heading"><h3>${title} <small> · ${compact(state.selectedQuantity,0)}套 · ${esc(find('suppliers',state.selectedSupplier)?.name||'')}</small></h3><div class="segmented">${modes.map(m=>`<button data-action="detail-mode" data-mode="${m}" class="${m===state.selectedMode?'active':''}">${labels[m]}</button>`).join('')}</div></div>`;
}
function renderDetail() {
  const target=$('resultDetail');if(!target)return;
  const r=selectedResult();
  if(!r){target.innerHTML=detailHeader('测算依据')+'<div class="empty-state">该运输方式没有结果，请调整条件重新测算。</div>';return;}
  if(state.detailTab==='fees')target.innerHTML=renderFees(r);
  else if(state.detailTab==='packaging')target.innerHTML=renderPackaging(r);
  else target.innerHTML=renderConditions(r);
}
function renderFees(r) {
  const fees=r.fees||[];
  const groups=[...new Set(fees.map(f=>f.group))];
  const table=fees.length?`<div class="table-wrap"><table><thead><tr><th>费用项目</th><th>计费基准</th><th class="number">计费数量</th><th class="number">单价</th><th class="number">原币金额</th><th>状态</th></tr></thead><tbody>${groups.map(group=>`<tr class="fee-group"><td colspan="6">${esc(labels[group]||group)}</td></tr>${fees.filter(f=>f.group===group).map(f=>`<tr><td>${esc(f.label)}<span class="tiny-label">${esc(f.source_id||'')}</span></td><td>${esc(basisLabels[f.basis]||f.basis)}</td><td class="number">${compact(f.quantity,4)}</td><td class="number">${money(f.unit_price,f.currency,4)}</td><td class="number total-number">${f.amount===null||f.amount===undefined?'—':money(f.amount,f.currency)}</td><td><span class="pill ${f.simulation_origin==='SIM-DEMO-POLICY'||['missing','pending'].includes(f.state)?'amber':'neutral'}">${esc(f.simulation_origin==='SIM-DEMO-POLICY'?'模拟补值':feeStateLabels[f.state]||f.state||'')}</span></td></tr>`).join('')}`).join('')}</tbody></table></div>`:'<div class="empty-state">尚无适用费用，货量可在包装依据中查看。</div>';
  const totals=Object.entries(r.original_totals||{}).map(([cur,val])=>`<span>${esc(cur)} 小计<strong>${numeric(val)}</strong></span>`).join('');
  const fx=find('fx',state.lastRequest?.fx_id);
  const fxText=fx?`预算汇率日期 ${fx.date} · ${Object.entries(fx.rates||{}).filter(([cur])=>cur!=='USD').map(([cur,rate])=>fx.currency_per_usd?.[cur]?`1 USD = ${fx.currency_per_usd[cur]} ${cur}`:`1 ${cur} = ${compact(rate,6)} USD`).join(' · ')}`:'';
  return detailHeader('费用明细')+table+`<div class="subtotal-line"><div>${totals||'暂无已计价项目'}<div class="fx-note">${esc(fxText)}</div></div><div>${r.complete?'总预算':'已知部分'}<strong>${money(r.budget_total??r.known_budget)}</strong></div></div>`+renderMessages(r.messages);
}
function renderPackaging(r) {
  const s=r.shipping||{},p=find('packagings',r.packaging_id),product=find('products',r.product_id),box=product?.carton;
  const stats=[['外箱数量',s.carton_count,'箱'],['完整托盘',s.full_pallets,'托'],['尾托剩余箱',s.tail_cartons,'箱'],['总托盘数',s.pallet_count,'托'],['交运体积',s.volume_m3,'m³'],['毛重（含包装）',s.gross_kg,'kg'],...(r.mode==='air'?[['空运材积重',s.volumetric_kg,'kg'],['空运计费重',s.chargeable_kg,'kg']]:[]),['起运车辆',s.origin_trucks,'车次'],['目的地派送',s.destination_trucks,'车次'],...(r.mode==='fcl'?[['海运柜数',s.container_count,s.container_type||'柜']]:[])];
  const units=Array.isArray(s.handling_units)?s.handling_units:[];
  const unitTable=units.length?`<div class="table-wrap"><table><thead><tr><th>交运件分组</th><th class="number">件数</th><th>外廓尺寸 · mm</th><th class="number">单件毛重 · kg</th><th class="number">单件体积 · m³</th></tr></thead><tbody>${units.map(u=>`<tr><td>${esc(u.label||u.type||u.kind||'托盘')}</td><td class="number">${compact(u.count??u.quantity??u.units,0)}</td><td>${esc([u.length_mm,u.width_mm,u.height_mm].map(x=>x??'—').join(' × '))}</td><td class="number">${compact(u.gross_kg??u.weight_kg,3)}</td><td class="number">${compact(u.volume_m3,6)}</td></tr>`).join('')}</tbody></table></div>`:'';
  return detailHeader('包装与装载依据')+`<div class="basis-grid">${stats.map(([key,v,u])=>`<div class="stat"><small>${key}</small><strong>${compact(v,3)} <span style="font:9px var(--sans)">${esc(u)}</span></strong></div>`).join('')}</div><div class="inline-condition">${esc(product?.name||'')} · ${esc(p?.name||'')}<br>${box?`外箱 ${box.length_mm}×${box.width_mm}×${box.height_mm} mm · ${box.units_per_carton}套／箱 · 毛重${box.gross_kg}kg／箱<br>`:''}${p?.pallet?`托盘 ${p.pallet.length_mm}×${p.pallet.width_mm}×${p.pallet.height_mm}mm（完整高度） · 限高${p.max_height_mm}mm · 每托限重${p.max_gross_kg}kg · ${p.max_layers}层上限`:''}</div>`+unitTable+`<div class="material-info-footer">车／柜数依据适用的已审核模拟装载模板，计量已包含托盘完整外廓与毛重。</div>`+renderMessages(r.messages);
}
function renderConditions(r) {
  const plan=find('rate_plans',r.rate_plan_id),origin=find('locations',state.lastRequest?.origin_id),dest=find('locations',state.lastRequest?.destination_id),service=find('services',state.lastRequest?.service_id);
  const estimate=r.estimate?.applied?r.estimate:null;
  const conditionItems=[...new Set([...(r.conditions||[]),...(estimate?.reasons||[]),...(service?.excluded||[])].map(messageText).filter(Boolean))];
  const sources=[...new Set([...(r.fees||[]).map(f=>f.source_id),estimate?.source_id].filter(Boolean))];
  return detailHeader('范围与来源')+`${estimate?`<div class="estimate-context"><span class="pill amber">模拟预估</span> 参数参考日期 ${esc(estimate.reference_date||'未指定')} · 以模拟参数完成本次预算</div>`:''}<dl class="definition-grid"><div><dt>提货点</dt><dd>${esc(origin?.name||'')}<span class="tiny-label">${esc(origin?.address||'')}</span></dd></div><div><dt>交付地点</dt><dd>${esc(dest?.name||'')}<span class="tiny-label">${esc(dest?.address||'')}</span></dd></div><div><dt>服务范围</dt><dd>${esc(service?.name||'')}<span class="tiny-label">${esc(service?.incoterm||'')} ${esc(service?.incoterms_version||'')}</span></dd></div><div><dt>费率方案</dt><dd>${esc(plan?.name||r.rate_plan_id||'暂无匹配')}</dd></div><div><dt>费率有效期</dt><dd>${esc(plan?.valid_from||'—')} 至 ${esc(plan?.valid_until||'—')}<span class="tiny-label">按计划启运日期匹配</span></dd></div><div><dt>资料版本</dt><dd>${esc(currentCatalog()?.version||'')}<span class="tiny-label">${esc(state.result.engine_version||'')}</span></dd></div></dl><ul class="condition-list">${conditionItems.map(x=>`<li>${esc(messageText(x))}</li>`).join('')}</ul><div class="material-info-footer">${sources.map(id=>{const doc=find('source_documents',id);return `${esc(doc?.name||id)}（${esc(id)}）`;}).join(' · ')}</div>`+renderMessages(r.messages);
}
function renderMessages(messages=[]) {
  return messages.length?`<div class="message-list" style="padding:0 16px">${messages.map(m=>`<div class="notice ${m.severity==='error'?'error':m.severity==='warning'?'warning':''}">${esc(messageText(m))}</div>`).join('')}</div>`:'';
}

function updateSnapshotBanner() {
  $('snapshotBanner').hidden=!state.readonly;
  $('snapshotBanner').innerHTML=state.readonly?`<div>正在查看 <strong>${esc(state.snapshot?.number||'')}</strong> · 已冻结当时的包装、费率与结果</div><button class="button ghost small" data-action="copy-snapshot">复制并调整</button>`:'';
}
async function saveSnapshot() {
  if(state.snapshot&&!state.dirty)return state.snapshot;
  if(state.readonly)return state.snapshot;
  if(state.dirty||!state.result)throw new Error('请先按当前条件计算，再保存。');
  const btn=$('saveEstimate');if(btn)btn.disabled=true;
  try{
    const snapshot=await post('/api/snapshots',{request:state.lastRequest,parent_id:state.parentId||undefined,expected_catalog_version:state.result.catalog_version||state.catalog.version});
    state.snapshot=snapshot;renderResults();toast(`已保存 ${snapshot.number}`);return snapshot;
  }catch(e){if(btn)btn.disabled=false;throw e;}
}
async function exportSnapshot(format) {
  if(state.dirty)throw new Error('条件已变更，请先重新计算。');
  const snapshot=await saveSnapshot();
  const url=`/api/snapshots/${encodeURIComponent(snapshot.id)}/export?format=${encodeURIComponent(format)}`;
  const response=window.FreightWorkspace?.enabled?await window.FreightWorkspace.exportFile(snapshot,format):await fetch(url);
  if(!response.ok){let message='文件导出失败，请稍后重试。';try{const v=await response.json();message=v.error||v.message||message;}catch{}throw new Error(message);}
  const disposition=response.headers.get('content-disposition')||'';
  let filename=disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if(filename){try{filename=decodeURIComponent(filename);}catch{}}
  filename=filename||disposition.match(/filename="?([^";]+)/i)?.[1]||`${snapshot.number}.${format==='inquiry'?'txt':format}`;
  const blob=await response.blob();downloadBlob(blob,filename);toast(`已导出 ${filename}`);
}
function downloadBlob(blob,name) {const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}

function navigate(view) {
  state.view=view;
  document.querySelectorAll('.view').forEach(x=>x.classList.toggle('active',x.id===`view-${view}`));
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.view===view));
  $('breadcrumbCurrent').textContent={quick:'快速测算',materials:'常用资料',rates:'货代费率',history:'测算记录'}[view];
  globalError('');
  if(view==='materials')renderMaterials();
  if(view==='rates')renderRates();
  if(view==='history')loadHistory();
}
function renderMaterials() {
  document.querySelectorAll('#materialTabs button').forEach(b=>b.classList.toggle('active',b.dataset.tab===state.materialTab));
  const target=$('materialContent');
  if(state.materialTab==='products'){
    target.innerHTML=`<div class="material-card-grid">${rows('products',state.catalog).map(p=>`<article class="material-card"><div class="code">${esc(p.id)}</div><h3>${esc(p.name)}</h3><p>${esc(p.composition||'')}<br>${esc(p.category||'')}</p><dl><div><dt>装箱数量</dt><dd>${p.carton?.units_per_carton??'—'}${esc(p.unit||'套')}／箱</dd></div><div><dt>单箱毛重</dt><dd>${esc(p.carton?.gross_kg||'—')} kg</dd></div><div style="grid-column:span 2"><dt>外箱尺寸</dt><dd>${esc([p.carton?.length_mm,p.carton?.width_mm,p.carton?.height_mm].join(' × '))} mm</dd></div></dl></article>`).join('')}</div><div class="material-info-footer">预置资料用于演示。下载资料源后可整理企业数据，通过资料 JSON 导入为新版本。</div>`;
  }else if(state.materialTab==='packagings'){
    target.innerHTML=`<div class="table-wrap"><table><thead><tr><th>包装方案</th><th>适用产品</th><th>托盘长×宽×完整高</th><th>限高／限重</th><th>排布与层数</th></tr></thead><tbody>${rows('packagings',state.catalog).map(p=>`<tr><td>${esc(p.name)}<span class="tiny-label">${esc(p.id)}</span></td><td>${esc(find('products',p.product_id,state.catalog)?.name||p.product_id)}</td><td>${esc([p.pallet?.length_mm,p.pallet?.width_mm,p.pallet?.height_mm].join(' × '))} mm</td><td>${esc(p.max_height_mm)} mm / ${esc(p.max_gross_kg)} kg</td><td>${(p.layout?.across_length||0)*(p.layout?.across_width||0)}箱／层 · 最多${p.max_layers}层</td></tr>`).join('')}</tbody></table></div><div class="surface-heading"><h3>装载模板</h3><small>模板有明确包装与设备适用范围</small></div><div class="material-card-grid">${rows('load_templates',state.catalog).map(t=>`<article class="material-card"><div class="code">${esc(t.id)}</div><h3>${esc(t.name)}</h3><dl><div><dt>托位</dt><dd>${t.slots}托／设备</dd></div><div><dt>总货重上限</dt><dd>${compact(t.max_total_kg,0)}kg</dd></div><div><dt>单件限高</dt><dd>${t.max_unit_height_mm}mm</dd></div><div><dt>模拟已审模板</dt><dd>${t.approved?'已预置':'待确认'}</dd></div></dl></article>`).join('')}</div>`;
  }else if(state.materialTab==='locations'){
    target.innerHTML=`<div class="material-card-grid">${rows('locations',state.catalog).map(l=>`<article class="material-card"><div class="code">${l.kind==='origin'?'ORIGIN':'DESTINATION'} · ${esc(l.id)}</div><h3>${esc(l.name)}</h3><p>${esc(l.country||'')} · ${esc(l.city||'')}<br>${esc(l.address||'')}</p></article>`).join('')}</div><div class="surface-heading"><h3>已预置运输路线</h3><small>仅匹配适用路线的费率</small></div><div class="table-wrap"><table><thead><tr><th>路线</th><th>空运节点</th><th>海运节点</th><th>货代费率</th></tr></thead><tbody>${rows('routes',state.catalog).map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.air_origin)} → ${esc(r.air_destination)}</td><td>${esc(r.sea_origin)} → ${esc(r.sea_destination)}</td><td>${rows('rate_plans',state.catalog).filter(p=>p.route_id===r.id).length}组</td></tr>`).join('')}</tbody></table></div>`;
  }else{
    if(!state.sources.length){target.innerHTML='<div class="loading-placeholder">正在准备资料源文件…</div>';loadSources();return;}
    target.innerHTML=`${window.FreightWorkspace?.enabled?'<div class="public-source-notice">以下文件是公开演示的预置资料。您修改或导入的当前版本保存在此浏览器，可用上方“导出资料 JSON”带走。</div>':''}<div class="source-list">${state.sources.map(s=>`<div class="source-row"><span class="source-icon">${icon('file')}</span><div><h4>${esc(s.name)}</h4><p>${esc(s.description||'')} ${s.bytes?` · ${compact(s.bytes/1024,1)} KB`:''}</p>${s.sha256?`<div class="source-hash">SHA-256 ${esc(s.sha256)}</div>`:''}</div><a class="button ghost small" href="${safeSourceURL(s.url||'/sources/'+encodeURIComponent(s.path))}" download>${icon('down')}下载</a></div>`).join('')}</div>`;
  }
}
function safeSourceURL(url) {try{const u=new URL(url,location.origin);return u.origin===location.origin&&u.pathname.startsWith('/sources/')?esc(u.pathname+u.search):'#';}catch{return '#';}}
async function loadSources() {
  try{const out=await api('/api/sources');state.sources=out.items||[];if(state.view==='materials'&&state.materialTab==='sources'){if(state.sources.length)renderMaterials();else $('materialContent').innerHTML='<div class="empty-state">资料源文件尚未准备完成，请稍后重试。<p><button class="table-action" data-action="refresh-sources">重新载入</button></p></div>';}}
  catch(e){if(state.view==='materials'&&state.materialTab==='sources')$('materialContent').innerHTML=`<div class="empty-state">${esc(e.message)}<p><button class="table-action" data-action="refresh-sources">重试资料源</button></p></div>`;}
}
function renderRates() {
  const filter=$('rateModeFilter').value;
  const plans=rows('rate_plans',state.catalog).filter(p=>filter==='all'||p.mode===filter);
  if(!plans.some(p=>p.id===state.ratePlanId))state.ratePlanId=plans[0]?.id;
  $('ratePlanList').innerHTML=plans.map(p=>`<button class="rate-plan-item ${p.id===state.ratePlanId?'active':''}" data-action="rate-plan" data-id="${esc(p.id)}"><span class="mini-mode">${esc(labels[p.mode])}</span>${esc(find('suppliers',p.supplier_id,state.catalog)?.name||p.supplier_id)}<small>${esc(find('routes',p.route_id,state.catalog)?.name||p.route_id)} · ${p.service_id==='door'?'到门':'到场站'}</small></button>`).join('');
  const plan=find('rate_plans',state.ratePlanId,state.catalog);
  if(!plan){$('rateDetail').innerHTML='<div class="empty-state">没有符合筛选条件的费率。</div>';return;}
  $('rateDetail').innerHTML=`<div class="rate-summary"><span class="pill amber">模拟费率</span><h2 style="margin-top:12px">${esc(plan.name)}</h2><p>${esc(plan.id)}</p></div><dl class="definition-grid"><div><dt>有效期</dt><dd>${esc(plan.valid_from)} 至 ${esc(plan.valid_until)}</dd></div><div><dt>适用方式</dt><dd>${esc(labels[plan.mode])} · ${plan.service_id==='door'?'到客户指定地点':'到目的场站'}</dd></div><div><dt>参考时效</dt><dd>${esc(transitText(plan))}<span class="tiny-label">${esc(plan.transit?.scope||'')}</span></dd></div></dl><div class="table-wrap"><table><thead><tr><th>费用项目</th><th>费用段</th><th>计费单位</th><th>币种</th><th class="number">单价（可编辑）</th></tr></thead><tbody>${(plan.fees||[]).map(f=>`<tr><td>${esc(f.label)}<span class="tiny-label">${esc(f.id)}</span></td><td>${esc(labels[f.group]||f.group)}</td><td>${esc(basisLabels[f.basis]||f.basis)}</td><td>${esc(f.currency)}</td><td class="number"><input class="rate-price-input" data-fee="${esc(f.id)}" value="${esc(f.unit_price??'')}" inputmode="decimal" aria-label="${esc(f.label)}单价" placeholder="待询价" ${f.state==='included'||f.state==='excluded'?'disabled':''}></td></tr>`).join('')}</tbody></table></div><div class="rate-footer"><p>单价留空表示待询价。保存新版本，已存测算仍保留原价格。</p><button id="saveRates" class="button primary">保存费率新版本</button></div><div class="material-info-footer">${(plan.conditions||[]).map(x=>esc(messageText(x))).join('<br>')}</div>`;
  $('saveRates').addEventListener('click',saveRateChanges);
}
async function saveRateChanges() {
  const button=$('saveRates');button.disabled=true;
  try{
    const updated=clone(state.catalog),plan=updated.rate_plans.find(p=>p.id===state.ratePlanId);
    $('rateDetail').querySelectorAll('input[data-fee]').forEach(input=>{
      const fee=plan.fees.find(f=>f.id===input.dataset.fee),v=input.value.trim();
      if(v!==''&&(!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(v)||!Number.isFinite(Number(v))))throw new Error(`${fee.label}请填写有效数值或留空。`);
      fee.unit_price=v===''?null:v;fee.state=v===''?'missing':'priced';
    });
    const response=await post('/api/catalog',{catalog:updated});
    state.catalog=response.catalog||response;state.sources=[];state.readonly=false;state.parentId=null;
    const request=state.lastRequest||state.catalog.default_request;fillForm(request);markDirty();renderRates();
    toast(`已保存资料新版本 ${response.version||state.catalog.version}`);
  }catch(e){toast(e.message);}finally{if($('saveRates'))$('saveRates').disabled=false;}
}
async function importCatalog(file) {
  try{
    if(file.size>4*1024*1024)throw new Error('资料JSON请控制在4MB以内。');
    const data=JSON.parse(await file.text());
    const response=await post('/api/catalog',{catalog:data});
    state.catalog=response.catalog||response;state.sources=[];state.readonly=false;state.snapshot=null;state.parentId=null;state.result=null;state.lastRequest=null;
    fillForm(state.catalog.default_request);renderMaterials();toast('资料已导入并保存为新版本。');
    await calculate();
  }catch(e){toast(`导入未完成：${e.message}`);}finally{$('catalogFile').value='';}
}

async function loadHistory() {
  try{
    $('historyContent').innerHTML='<div class="loading-placeholder">正在载入保存记录…</div>';
    const response=await api('/api/snapshots?q='+encodeURIComponent($('historySearch').value.trim()));
    const list=response.items||[];$('historyCount').textContent=`${list.length} 条记录`;
    $('historyContent').innerHTML=list.length?`<div class="table-wrap"><table><thead><tr><th>测算编号</th><th>产品 / 目的地</th><th>数量情景</th><th>保存时间</th><th>操作</th></tr></thead><tbody>${list.map(s=>`<tr><td><button class="table-action history-number" data-action="open-snapshot" data-id="${esc(s.id)}">${esc(s.number||s.id)}</button><span class="tiny-label">版本 ${s.revision||1}</span></td><td>${esc(s.product_name||s.product||'内部运费测算')}<span class="tiny-label">${esc(s.destination_name||s.destination||s.route_label||'')}</span></td><td>${esc((s.quantities||s.request?.quantities||[]).map(q=>compact(q,0)).join(' / ')||s.quantity||'—')}</td><td>${esc(formatDate(s.created_at))}</td><td><button class="history-row-button" data-action="open-snapshot" data-id="${esc(s.id)}">查看与导出 →</button></td></tr>`).join('')}</tbody></table></div>`:`<div class="empty-state">${icon('history')}暂无保存记录<p>在快速测算中保存一次，即可在这里回查并导出。</p></div>`;
  }catch(e){$('historyContent').innerHTML=`<div class="empty-state">${esc(e.message)}</div>`;}
}
function formatDate(value) {if(!value)return '—';const d=new Date(value);return Number.isNaN(d.valueOf())?value:d.toLocaleString('zh-CN',{timeZone:'Asia/Singapore',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});}
async function openSnapshot(id) {
  state.requestGeneration++;
  try{
    const snapshot=await api('/api/snapshots/'+encodeURIComponent(id));
    state.snapshot=snapshot;state.result=snapshot.result;state.lastRequest=snapshot.request||snapshot.result.request;state.readonly=true;state.dirty=false;state.parentId=snapshot.id;
    state.selectedQuantity=state.lastRequest.quantities[0];state.selectedSupplier=state.lastRequest.supplier_ids[0];state.selectedMode=state.lastRequest.modes[0];
    fillForm(state.lastRequest);navigate('quick');renderResults();window.scrollTo({top:0,behavior:'smooth'});
  }catch(e){toast(e.message);}
}
async function copySnapshot() {
  const request=clone(state.lastRequest),parent=state.snapshot?.id;
  state.readonly=false;state.snapshot=null;state.parentId=parent;state.dirty=true;
  fillForm(request);updateSnapshotBanner();await calculate();toast('已复制为可调整测算，保存时生成新版本。');
}
async function parseInquiry() {
  const button=$('parseInquiry');button.disabled=true;$('parseFeedback').textContent='';
  try{
    const text=$('inquiryText').value.trim();if(!text)throw new Error('请先输入询价文字。');
    const response=await post('/api/inquiry/parse',{text});
    if(!response.draft||!Object.keys(response.draft).length)throw new Error('未识别到可填入字段，请使用产品、数量、目的地、启运日期等约定字段。');
    const request={...(state.lastRequest||state.catalog.default_request),...response.draft};
    state.readonly=false;state.snapshot=null;state.parentId=null;fillForm(request);markDirty();navigate('quick');$('parseDialog').close();
    toast((response.notes||[]).map(messageText).filter(Boolean).join('；')||'已带入输入草稿，请核对后计算。');
  }catch(e){$('parseFeedback').textContent=e.message;}finally{button.disabled=false;}
}
async function importInquiryExcel(file) {
  const button=$('importInquiryExcel');button.disabled=true;$('parseFeedback').textContent='正在读取约定询价表…';
  try{
    if(!/\.xlsx$/i.test(file.name)||file.size>3*1024*1024)throw new Error('请选择3MB以内的.xlsx询价模板。');
    const b64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件未能读取，请重新选择。'));reader.readAsDataURL(file);});
    const response=await post('/api/inquiry/import',{file_base64:b64});
    if(!response.draft||!Object.keys(response.draft).length)throw new Error('询价表没有可填入内容，请检查“询价输入”工作表。');
    const request={...(state.lastRequest||state.catalog.default_request),...response.draft};
    state.readonly=false;state.snapshot=null;state.parentId=null;fillForm(request);markDirty();navigate('quick');$('parseDialog').close();
    toast((response.notes||[]).map(messageText).filter(Boolean).join('；')||'已带入Excel询价草稿，请核对后计算。');
  }catch(e){$('parseFeedback').textContent=e.message;}finally{button.disabled=false;$('inquiryExcelFile').value='';}
}

function bindEvents() {
  document.querySelector('.brand').addEventListener('click',e=>{e.preventDefault();navigate('quick');});
  document.querySelectorAll('.nav-item').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.view)));
  $('quickForm').addEventListener('submit',e=>{e.preventDefault();calculate();});
  $('quickForm').addEventListener('input',e=>{if(e.target.id!=='product')markDirty();});
  $('quickForm').addEventListener('change',e=>{if(e.target.id==='product')refreshPackaging();if(e.target.id==='demoEstimation')updateEstimationMode();markDirty();});
  $('resetDemo').addEventListener('click',async()=>{state.requestGeneration++;state.readonly=false;state.snapshot=null;state.parentId=null;state.result=null;state.lastRequest=null;fillForm(state.catalog.default_request);navigate('quick');await calculate();});
  $('openParse').addEventListener('click',()=>{$('parseFeedback').textContent='';$('parseDialog').showModal();});
  $('parseInquiry').addEventListener('click',parseInquiry);
  $('importInquiryExcel').addEventListener('click',()=>$('inquiryExcelFile').click());
  $('inquiryExcelFile').addEventListener('change',()=>{if($('inquiryExcelFile').files[0])importInquiryExcel($('inquiryExcelFile').files[0]);});
  $('materialTabs').addEventListener('click',e=>{const b=e.target.closest('button[data-tab]');if(b){state.materialTab=b.dataset.tab;renderMaterials();}});
  $('exportCatalog').addEventListener('click',()=>downloadBlob(new Blob([JSON.stringify(state.catalog,null,2)],{type:'application/json'}),`业务资料_${state.catalog.version}.json`));
  $('importCatalog').addEventListener('click',()=>$('catalogFile').click());
  $('catalogFile').addEventListener('change',()=>{if($('catalogFile').files[0])importCatalog($('catalogFile').files[0]);});
  $('rateModeFilter').addEventListener('change',renderRates);
  $('refreshHistory').addEventListener('click',loadHistory);
  let searchTimer;$('historySearch').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(loadHistory,250);});
  document.addEventListener('click',async e=>{
    const close=e.target.closest('[data-close]');if(close){$(close.dataset.close)?.close();return;}
    const el=e.target.closest('[data-action]');if(!el||el.disabled)return;
    try{
      switch(el.dataset.action){
        case 'quantity':state.selectedQuantity=Number(el.dataset.qty);renderResults();break;
        case 'supplier':state.selectedSupplier=el.dataset.id;renderResults();break;
        case 'detail-tab':state.detailTab=el.dataset.tab;renderResults();break;
        case 'detail-mode':state.selectedMode=el.dataset.mode;renderDetail();break;
        case 'show-mode':state.selectedMode=el.dataset.mode;state.detailTab='fees';renderResults();$('resultDetail')?.scrollIntoView({behavior:'smooth',block:'center'});break;
        case 'export':el.disabled=true;try{await exportSnapshot(el.dataset.format);}finally{el.disabled=false;}break;
        case 'rate-plan':state.ratePlanId=el.dataset.id;renderRates();break;
        case 'refresh-sources':loadSources();break;
        case 'open-snapshot':await openSnapshot(el.dataset.id);break;
        case 'copy-snapshot':await copySnapshot();break;
      }
    }catch(error){toast(error.message);}
  });
}

async function init() {
  if(window.FreightWorkspace?.enabled){
    $('workspaceCaption').textContent='独立演示空间';
    $('workspaceStorageHint').textContent='修改与记录仅保存在此浏览器';
    $('workspaceFooterHint').textContent='公开演示使用模拟资料；修改与记录保存在此浏览器，清理浏览器后会丢失。实际运输请另行确认。';
  }
  bindEvents();
  try{
    state.catalog=await api('/api/catalog');
    fillForm(state.catalog.default_request);
    await calculate();
  }catch(e){globalError(`工作台载入失败：${e.message}`);$('resultArea').innerHTML=`<div class="empty-state">${window.FreightWorkspace?.enabled?'请检查网络与浏览器存储设置，刷新页面即可重试。':'请确认本地服务已启动，刷新页面即可重试。'}</div>`;}
}
init();
