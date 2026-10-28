/* Documents are rendered from the immutable snapshot. No freight arithmetic,
 * HTML parsing, remote export service, CDN script, or spreadsheet formula runs here. */
import {jsPDF} from 'jspdf';
import {autoTable} from 'jspdf-autotable';
import ExcelJS from 'exceljs';

const MODE = {air: '空运', fcl: '海运整柜', lcl: '海运拼箱'};
const STATE = {estimated: '模拟预算', simulated: '模拟预估（虚拟参数）', partial: '费用待补充', invalid: '资料待补充', historical: '历史参考', not_applicable: '方案不适用'};
const FEE_STATE = {priced: '已计价', missing: '待询价', included: '已含', excluded: '不计入', not_applicable: '不适用'};
const GROUP = {origin: '起运地', freight: '干线', destination: '目的地', main: '干线'};
const BASIS = {shipment: '票', pallet: '板', carton: '箱', chargeable_kg: '计费kg', container: '柜', origin_truck: '提货车', destination_truck: '派送车', truck: '车', kg: 'kg', cbm: 'm³', revenue_ton: '计费吨'};
const FONT_NAME = 'FreightChinese';
const BRAND = '三文鱼AI  WX：supersalmon';
let fontPromise;

function clean(value, fallback = '') {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'boolean') return value ? '是' : '否';
  return String(value).replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, '');
}
const records = value => Array.isArray(value) ? value.filter(item => item && typeof item === 'object' && !Array.isArray(item)) : [];
function numeric(value, fallback = '待补充') {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}
function format(value, decimals = 2, fallback = '待补充') {
  const number = numeric(value, null);
  return number === null ? fallback : number.toLocaleString('en-US', {minimumFractionDigits: decimals, maximumFractionDigits: decimals});
}
function checked(snapshot) {
  if (!snapshot || !snapshot.id || !snapshot.number) throw new Error('请先保存测算，再导出文件。');
  if (!snapshot.request || !snapshot.result) throw new Error('保存快照缺少输入或计算结果。');
  const rows = records(snapshot.result.results);
  if (!rows.length) throw new Error('当前快照没有可导出的测算方案。');
  return {req: snapshot.request, result: snapshot.result, rows, catalog: snapshot.catalog_snapshot || {}};
}
function savedTime(value) {
  const raw = clean(value);
  if (!/[zZ]|[+-]\d\d:\d\d$/.test(raw)) return raw ? raw + '（时区未注明）' : '';
  const date = new Date(raw);
  if (!Number.isFinite(date.getTime())) return raw;
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Singapore', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'}).formatToParts(date);
  const get = type => parts.find(part => part.type === type)?.value;
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}（UTC+08:00）`;
}
function transit(row) {
  const t = row.transit || {};
  if (typeof t === 'string') return t;
  const lo = t.min ?? t.min_days, hi = t.max ?? t.max_days;
  return lo !== undefined && hi !== undefined ? `${lo}-${hi}自然日` : clean(t.label || t.text, '待货代确认');
}
function conditions(row) {
  return (row.conditions || []).map(value => typeof value === 'object' && value ? clean(value.text || value.message) : clean(value)).filter(Boolean);
}
const status = row => STATE[row.status] || '费用待确认';
const scope = row => row.complete && row.budget_total != null ? '所选范围预算已齐' : '已知部分，完整总额待补充';
const mode = row => MODE[row.mode] || clean(row.mode);
const label = row => `${clean(row.quantity)}套 ${mode(row)} ${clean(row.supplier_name)}`;
function fxText(fx) {
  if (!fx || typeof fx !== 'object' || Array.isArray(fx)) return clean(fx);
  const inverse = fx.currency_per_usd || {}, target = fx.currency || 'USD';
  return Object.entries(fx.rates || {}).filter(([currency]) => currency !== target).map(([currency, rate]) =>
    currency in inverse ? `1 ${target} = ${clean(inverse[currency])} ${currency}` : `1 ${currency} = ${clean(rate)} ${target}`
  ).join('；') + (fx.date ? `（${clean(fx.date)}预算汇率）` : '');
}
function metadata(snapshot) {
  const {req, result, rows, catalog} = checked(snapshot);
  const lookup = (collection, id) => records(catalog[collection]).find(row => row.id === id) || {};
  const product = lookup('products', req.product_id), origin = lookup('locations', req.origin_id), dest = lookup('locations', req.destination_id);
  return [
    ['测算编号', snapshot.number], ['保存时间', savedTime(snapshot.created_at)],
    ['数据性质', result.is_demo !== false ? '模拟演示数据，非市场成交价' : '用户维护资料'],
    ['产品', rows[0].product_name || product.name || req.product_id],
    ['数量档位', (req.quantities || []).join('、') + '套'], ['包装', rows[0].packaging_name || req.packaging_id],
    ['起运点', origin.name || req.origin_id], ['目的地', dest.name || req.destination_id],
    ['目的地地址', dest.address || dest.display_address || '按所选服务模板'],
    ['服务范围', req.service_id === 'door' ? '到客户指定地点' : '到港／机场场站'],
    ['计划启运日', req.departure_date], ['预算币种', result.currency || 'USD'],
    ['BU／需求编号', [req.metadata?.bu || '', req.metadata?.reference || ''].join(' / ').replace(/^[ /]+|[ /]+$/g, '')],
    ['资料版本', catalog.version || snapshot.catalog_hash || '快照内版本'], ['规则版本', snapshot.rule_version || result.engine_version]
  ];
}

// Keep the six-sheet contract and numeric cell positions in portable_documents.py.
function workbookSheets(snapshot) {
  const {req, result, rows, catalog} = checked(snapshot), number = clean(snapshot.number), meta = metadata(snapshot);
  const summary = [[], ['内部运费测算单'], ['数据性质', '模拟预算快照；改条件后回工作台重算。'], ...meta,
    [], ['数量(套)', '运输方式', '供应商', '预算总额', '预算币种', '每套预算', '费用范围', '参考时效']];
  const packaging = [[], ['包装明细'], [`测算编号：${number}`], ['情景', '交运件类型', '件数', '每件长mm', '每件宽mm', '每件高mm', '每件毛重kg', '计量说明']];
  const basis = [[], ['计费依据'], [`测算编号：${number}`], ['情景', '数量(套)', '外箱数', '托盘数', '体积m³', '毛重kg', '材积重kg', '计费重kg', '提货车次', '派送车次', '柜型', '柜数', '费率方案']];
  const fees = [[], ['费用明细'], [`测算编号：${number}；原币金额按保存快照列示`], ['情景', '服务段', '费用项目', '计费单位', '计费数量', '单价', '币种', '原币金额', '状态', '来源', '覆盖服务']];
  const compare = [[], ['情景对比'], [`测算编号：${number}`], ['数量(套)', '运输方式', '供应商', '包装方案', '原币USD小计', '原币CNY小计', '原币AUD小计', '预算USD', '每套USD', '已知预算USD', '状态', '参考时效']];
  const sources = [[], ['来源与待询价项'], [`测算编号：${number}；预算汇率与资料随本快照固定`], ['类型', '情景／编号', '内容', '来源／依据', '备注']];
  for (const row of rows) {
    const name = label(row), s = row.shipping || {};
    summary.push([row.quantity, mode(row), row.supplier_name, numeric(row.budget_total, '待补齐'), result.currency || 'USD', numeric(row.per_set, '待补齐'), scope(row), transit(row)]);
    const units = records(s.handling_units);
    for (const unit of units) {
      let dims = unit.dimensions_mm || {};
      if (Array.isArray(dims)) dims = {length: dims[0], width: dims[1], height: dims[2]};
      packaging.push([name, unit.label || unit.type || unit.kind || '交运件', numeric(unit.count ?? unit.quantity), numeric(unit.length_mm ?? dims.length), numeric(unit.width_mm ?? dims.width), numeric(unit.height_mm ?? dims.height), numeric(unit.gross_kg ?? unit.weight_kg), unit.note || '按交运外廓计量']);
    }
    if (!units.length) packaging.push([name, '交运合计', s.pallet_count || s.carton_count, null, null, null, numeric(s.gross_kg), '详见计费依据']);
    basis.push([name, row.quantity, s.carton_count, s.pallet_count, numeric(s.volume_m3), numeric(s.gross_kg), row.mode === 'air' ? numeric(s.volumetric_kg) : '', row.mode === 'air' ? numeric(s.chargeable_kg) : '', s.origin_trucks, s.destination_trucks, row.mode === 'fcl' ? s.container_type : '', row.mode === 'fcl' ? s.container_count : '', row.rate_plan_id]);
    for (const fee of records(row.fees)) {
      fees.push([name, GROUP[fee.group] || fee.group, fee.label, BASIS[fee.basis] || fee.basis, numeric(fee.quantity), numeric(fee.unit_price, '待询价'), fee.currency, numeric(fee.amount, '待询价'), fee.simulation_origin ? '模拟补值' : FEE_STATE[fee.state] || fee.state, fee.source_id, (fee.covers || []).join('、')]);
      if (fee.state === 'missing') sources.push(['待询价', name, fee.label, fee.source_id || '尚未提供', '完整预算待此项补价']);
    }
    const original = row.original_totals || {};
    compare.push([row.quantity, mode(row), row.supplier_name, row.packaging_name, numeric(original.USD, ''), numeric(original.CNY, ''), numeric(original.AUD, ''), numeric(row.budget_total, '待补齐'), numeric(row.per_set, '待补齐'), numeric(row.known_budget, '待补齐'), status(row), transit(row)]);
    for (const msg of records(row.messages)) sources.push(['条件', name, msg.text || msg.message, msg.code, msg.field]);
    for (const condition of conditions(row)) sources.push(['适用条件', name, condition, row.rate_plan_id, '']);
    if (row.fx && !Array.isArray(row.fx) && typeof row.fx === 'object') sources.push(['预算汇率', name, fxText(row.fx), req.fx_id, '按原币小计折算，非逐行折算']);
    else for (const fx of records(row.fx)) sources.push(['预算汇率', name, JSON.stringify(fx), req.fx_id, '按原币小计折算，非逐行折算']);
  }
  for (const src of records(catalog.source_documents)) sources.push(['资料来源', src.id, src.name || src.title || src.description, src.url || src.path || src.kind, src.description || src.note]);
  sources.push(['版本', number, snapshot.catalog_hash, snapshot.rule_version || result.engine_version, '导出不重新计算']);
  sources.push(['制作', BRAND]);
  return [
    {name: '询价摘要', rows: summary, header: 3 + meta.length + 2, widths: [22,29,29,20,15,19,35,23], wrap: [1,6], formats: {0:'#,##0',5:'#,##0.0000'}},
    {name: '包装明细', rows: packaging, header: 4, widths: [40,20,12,16,16,16,18,28], wrap: [0,7], formats: {2:'#,##0',3:'#,##0',4:'#,##0',5:'#,##0',6:'#,##0.000'}},
    {name: '计费依据', rows: basis, header: 4, widths: [40,14,12,12,18,18,18,18,14,14,15,12,35], wrap: [0], formats: {1:'#,##0',2:'#,##0',3:'#,##0',4:'#,##0.0000',5:'#,##0.000',6:'#,##0.000',7:'#,##0.000',8:'#,##0',9:'#,##0',11:'#,##0'}},
    {name: '费用明细', rows: fees, header: 4, widths: [40,14,31,16,18,18,12,20,16,29,37], wrap: [0,2,10]},
    {name: '情景对比', rows: compare, header: 4, widths: [14,16,23,25,20,20,20,20,20,22,22,24], wrap: [3], formats: {0:'#,##0',8:'#,##0.0000'}},
    {name: '来源与缺项', rows: sources, header: 4, widths: [18,42,70,45,48], wrap: [1,2,3,4]}
  ];
}

export async function exportXlsx(snapshot) {
  const book = new ExcelJS.Workbook();
  book.creator = '三文鱼AI';
  for (const definition of workbookSheets(snapshot)) {
    const sheet = book.addWorksheet(definition.name, {views: [{showGridLines: false, state: 'frozen', ySplit: definition.header}], pageSetup: {orientation: 'landscape', fitToPage: true, fitToWidth: 1, fitToHeight: 0, printTitlesRow: `1:${definition.header}`}});
    sheet.columns = definition.widths.map(width => ({width}));
    definition.rows.forEach((values, index) => {
      const row = sheet.getRow(index + 1), header = index + 1 === definition.header, title = index === 1;
      let lines = 1;
      values.forEach((value, ci) => {
        if (value === null || value === undefined) return;
        const cell = row.getCell(ci + 1);
        // A plain string value is serialized as a shared string, even when it
        // starts with =, +, -, @ or looks like a URL. Never assign a formula object.
        cell.value = typeof value === 'number' || typeof value === 'boolean' ? value : clean(value);
        cell.font = {name: 'Arial', size: title ? 14 : 10, color: {argb: header ? 'FFFFFFFF' : 'FF193342'}, bold: header || title};
        cell.numFmt = definition.formats?.[ci] || '#,##0.00';
        const wrap = header || definition.wrap.includes(ci);
        cell.alignment = {vertical: 'middle', wrapText: wrap, ...(header ? {horizontal: 'center'} : {})};
        if (header) cell.fill = {type: 'pattern', pattern: 'solid', fgColor: {argb: 'FF173F4C'}};
        if (wrap && typeof value === 'string') {
          const visual = Array.from(value).reduce((count, c) => count + (c.codePointAt(0) > 255 ? 2 : 1), 0);
          lines = Math.max(lines, Math.ceil(visual / Math.max(1, definition.widths[ci] - 2)));
        }
      });
      row.height = Math.max(title ? 29 : header ? 27 : 23, Math.min(250, lines * 14 + 9));
    });
  }
  return book.xlsx.writeBuffer();
}

async function fontBase64() {
  if (!fontPromise) fontPromise = (async () => {
    const response = await fetch('/fonts/NotoSansSC-Regular.ttf', {cache: 'force-cache'});
    if (!response.ok) throw new Error('导出中文PDF的字体未能加载，请稍后重试。');
    const bytes = new Uint8Array(await response.arrayBuffer());
    let binary = '';
    for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
    return btoa(binary);
  })().catch(error => {fontPromise = null; throw error;});
  return fontPromise;
}

export async function exportPdf(snapshot) {
  const {req, result, rows, catalog} = checked(snapshot);
  const doc = new jsPDF({orientation: 'portrait', unit: 'mm', format: 'a4', compress: true, putOnlyUsedFonts: true});
  doc.addFileToVFS('NotoSansSC-Regular.ttf', await fontBase64());
  doc.addFont('NotoSansSC-Regular.ttf', FONT_NAME, 'normal');
  doc.setFont(FONT_NAME, 'normal');
  // jsPDF publishes some font parser failures as console events. Refuse the
  // download if registration silently fell back to an unsupported font.
  if (!doc.getFont().metadata?.characterToGlyph?.('中'.codePointAt(0))) {
    throw new Error('导出中文PDF的字体无法解析，请刷新页面后重试。');
  }
  doc.setProperties({title: `内部运费测算单 ${clean(snapshot.number)}`, author: '三文鱼AI', subject: '冻结预算快照，不重新计算'});
  const margin = 15, width = 180, bottom = 276;
  let y = margin;
  const page = () => {doc.addPage(); y = margin;};
  function text(value, size = 8, gap = 1) {
    const content = clean(value);
    if (!content) return;
    doc.setFont(FONT_NAME, 'normal').setFontSize(size).setTextColor('#193342');
    const lines = doc.splitTextToSize(content, width), lineHeight = size * 0.3528 * 1.3;
    for (const line of lines) {
      if (y + lineHeight > bottom) page();
      doc.text(line, margin, y + lineHeight * 0.78);
      y += lineHeight;
    }
    y += gap;
  }
  function table(head, body, widths, fontSize = 8) {
    if (y + 15 > bottom) page();
    autoTable(doc, {startY: y, ...(head ? {head: [head.map(clean)]} : {}), body: body.map(row => row.map(value => clean(value))),
      margin: {top: margin, left: margin, right: margin, bottom: 21}, tableWidth: width, theme: 'grid',
      styles: {font: FONT_NAME, fontStyle: 'normal', fontSize, cellPadding: 1.5, textColor: '#193342', lineColor: '#D1DEDF', lineWidth: 0.15, overflow: 'linebreak', valign: 'top'},
      headStyles: {font: FONT_NAME, fontStyle: 'normal', fillColor: '#173F4C', textColor: '#FFFFFF'},
      bodyStyles: {font: FONT_NAME, fontStyle: 'normal'}, alternateRowStyles: {fillColor: '#EDF3F3'},
      columnStyles: Object.fromEntries(widths.map((cellWidth, i) => [i, {cellWidth}])),
      showHead: 'everyPage', rowPageBreak: 'avoid'});
    y = doc.lastAutoTable.finalY + 4;
  }
  text('内部运费测算单', 21, 4);
  text(`${clean(snapshot.number)}    ${savedTime(snapshot.created_at)}`);
  text(result.is_demo !== false ? '模拟演示资料。用于所选运输范围的内部预算，非货代成交报价。' : '用户维护资料。用于所选运输范围的内部预算，实际承运条件请向货代确认。');
  table(null, metadata(snapshot), [32,148]);
  if (req.metadata?.note) text('询价备注：' + clean(req.metadata.note));
  text('空海运方案比较', 13);
  table(['数量', '运输', '供应商', `总预算 ${result.currency || 'USD'}`, `每套 ${result.currency || 'USD'}`, '参考时效'],
    rows.map(row => [clean(row.quantity) + '套', mode(row), row.supplier_name, format(row.budget_total), format(row.per_set, 4), transit(row)]), [17,21,31,40,37,34], 7.5);
  for (const row of rows) if (row.budget_total == null) text(`${label(row)}：已知预算 ${result.currency || 'USD'} ${format(row.known_budget)}；完整预算待补齐。`);
  text('原币费用与预算汇率随本次测算保存。参考时效不代表舱位或订舱承诺。');
  for (const row of rows) {
    page();
    text(label(row), 13, 3);
    text(clean(row.route_label));
    text(`${scope(row)}；${status(row)}`);
    text('费率方案：' + clean(row.rate_plan_id, '尚未匹配'));
    const validity = row.validity || {}, estimate = row.estimate || {}, originalValidity = estimate.original_validity || validity;
    text(`原费率有效期：${clean(originalValidity.valid_from, '未提供')} 至 ${clean(originalValidity.valid_until, '未提供')}；启运日 ${clean(req.departure_date)}；${originalValidity.matched === false ? '启运日期未匹配原费率有效期' : '按保存快照列示'}`);
    if (estimate.applied) {
      text('模拟依据：' + clean(estimate.source_id) + '；参考模板：' + clean(estimate.reference_plan_id) + '；参考日期：' + clean(estimate.reference_date));
      for (const reason of estimate.reasons || []) text('模拟原因：' + clean(reason));
    }
    const s = row.shipping || {};
    table(['包装与计费', '数值', '包装与计费', '数值'], [
      ['外箱数', s.carton_count, '托盘数', s.pallet_count],
      ['交运体积m³', format(s.volume_m3, 4), '总毛重kg', format(s.gross_kg, 1)],
      row.mode === 'air' ? ['空运材积kg', format(s.volumetric_kg, 0), '空运计费kg', format(s.chargeable_kg, 0)] : ['柜型', s.container_type || '待确认', '柜数', s.container_count],
      ['提货车次', s.origin_trucks, '派送车次', s.destination_trucks]
    ], [43,47,43,47]);
    const units = records(s.handling_units);
    if (units.length) table(['交运件', '件数', '长×宽×高 mm', '每件毛重kg'], units.map(unit => {
      let dims = unit.dimensions_mm || {};
      if (Array.isArray(dims)) dims = {length: dims[0], width: dims[1], height: dims[2]};
      return [unit.label || unit.type || unit.kind || '交运件', clean(unit.count ?? unit.quantity), [unit.length_mm ?? dims.length, unit.width_mm ?? dims.width, unit.height_mm ?? dims.height].map(value => clean(value, '待确认')).join(' × '), format(unit.gross_kg ?? unit.weight_kg, 3)];
    }), [42,20,78,40]);
    text('费用明细', 11);
    table(['费用项目／来源', '服务段', '计费数量', '单价', '币种', '原币金额'], records(row.fees).map(fee => [
      clean(fee.label) + (fee.simulation_origin ? '〔模拟补值〕' : '') + '\n来源：' + clean(fee.source_id, '待提供'), GROUP[fee.group] || fee.group,
      format(fee.quantity) + ' ' + (BASIS[fee.basis] || clean(fee.basis)), format(fee.unit_price, 2, '待询价'), fee.currency, format(fee.amount, 2, FEE_STATE[fee.state] || '待询价')
    ]), [62,18,33,25,15,27], 7.5);
    text('原币小计：' + Object.entries(row.original_totals || {}).map(([currency, amount]) => `${currency} ${format(amount)}`).join('；'));
    text(`预算折算 ${result.currency || 'USD'} ${format(row.budget_total)}；每套 ${result.currency || 'USD'} ${format(row.per_set, 4)}`, 10);
    if (row.fx) text('预算汇率：' + (Array.isArray(row.fx) ? row.fx.map(fx => JSON.stringify(fx)).join('；') : fxText(row.fx)));
    const shownReasons = new Set((estimate.reasons || []).map(reason => clean(reason)));
    const notes = [...new Set([...conditions(row), ...records(row.messages).map(msg => clean(msg.text || msg.message))])].filter(note => !shownReasons.has(note));
    if (notes.length) {text('范围与条件', 10); notes.forEach(note => text(note));}
  }
  page();
  text('资料来源与版本', 13);
  table(['编号', '资料／说明', '来源'], records(catalog.source_documents).map(src => [src.id, [src.name || src.title || src.description, src.description || src.note].filter(Boolean).join('\n'), src.url || src.path || src.kind]), [34,85,61], 7.5);
  text('资料版本：' + clean(catalog.version || snapshot.catalog_hash));
  text('快照摘要：' + clean(snapshot.catalog_hash));
  text('规则版本：' + clean(snapshot.rule_version || result.engine_version));
  text('所有金额直接读取已保存快照，导出不重新计算。');
  const pages = doc.getNumberOfPages();
  for (let p = 1; p <= pages; p++) {
    doc.setPage(p).setFont(FONT_NAME, 'normal').setFontSize(7).setTextColor('#5F7781');
    doc.text(`${clean(snapshot.number)}  内部测算`, margin, 284);
    doc.text(BRAND, margin, 289);
    doc.text(`第 ${p} / ${pages} 页`, 195, 289, {align: 'right'});
  }
  return doc.output('arraybuffer');
}

export async function exportFile(snapshot, requestedFormat) {
  checked(snapshot);
  let bytes, mime;
  if (requestedFormat === 'pdf') {bytes = await exportPdf(snapshot); mime = 'application/pdf';}
  else if (requestedFormat === 'xlsx') {bytes = await exportXlsx(snapshot); mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';}
  else throw new Error('不支持该导出格式。');
  return new Response(bytes, {status: 200, headers: {'Content-Type': mime, 'Cache-Control': 'no-store'}});
}
