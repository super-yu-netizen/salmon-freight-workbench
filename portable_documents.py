"""Portable snapshot exports for Cloudflare Python Workers.

Business layout and field selection mirror documents.py.  This module never
launches Node, imports a private runtime, or reads a machine-specific font path.
XLSX uses pure-Python XlsxWriter; PDF embeds the supplied redistributable font.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO
import hashlib
import json
import re
from typing import Any

_FONT_CACHE = {}


def _font(font_bytes=None):
    if not isinstance(font_bytes, bytes) or not font_bytes:
        raise ExportError('导出中文PDF的字体尚未准备好，请稍后再试。')
    key = hashlib.sha256(font_bytes).hexdigest()[:16]
    if key not in _FONT_CACHE:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        name = 'FreightChinese' + key
        pdfmetrics.registerFont(TTFont(name, BytesIO(font_bytes)))
        _FONT_CACHE[key] = name
    return _FONT_CACHE[key]


def workbook_bytes(sheets, preview_dir=None):
    """Serialize an immutable snapshot; formulas and URLs are always literals."""
    import xlsxwriter
    stream = BytesIO()
    book = xlsxwriter.Workbook(stream, {'in_memory': True, 'strings_to_formulas': False,
                                     'strings_to_urls': False, 'strings_to_numbers': False})
    cache = {}
    def style(header=False, title=False, wrap=False, number='#,##0.00'):
        key=(header,title,wrap,number)
        if key not in cache:
            opts={'font_name':'Arial','font_size':10,'font_color':'#193342',
                  'valign':'vcenter','num_format':number,'text_wrap':wrap}
            if header:opts.update(bold=True,bg_color='#173F4C',font_color='#FFFFFF',align='center')
            if title:opts.update(bold=True,font_size=14,font_color='#153A4A')
            cache[key]=book.add_format(opts)
        return cache[key]
    for definition in sheets:
        sheet=book.add_worksheet(definition['name'])
        sheet.hide_gridlines(2)
        header_rows=set(definition.get('header_rows',[]))
        widths=definition.get('widths',[])
        for col,width in enumerate(widths):sheet.set_column(col,col,width)
        freeze=definition.get('freeze_rows') or max(header_rows or [0])
        if freeze:sheet.freeze_panes(freeze,0)
        for ri,row in enumerate(definition['rows']):
            is_header=(ri+1) in header_rows
            is_title=ri==1
            height=29 if is_title else 27 if is_header else 23
            max_lines=1
            for ci,value in enumerate(row):
                if value is None:continue
                number=definition.get('number_formats',{}).get(str(ci),'#,##0.00')
                wrap=is_header or ci in definition.get('wrap_columns',[])
                fmt=style(is_header,is_title,wrap,number)
                # Explicit write_string prevents workbook formula and URL interpretation.
                if isinstance(value,str):
                    value=_clean(value)
                    sheet.write_string(ri,ci,value,fmt)
                    if wrap:
                        width=widths[ci] if ci<len(widths) else 18
                        visual=sum(2 if ord(c)>255 else 1 for c in value)
                        max_lines=max(max_lines,(visual+max(1,int(width)-2)-1)//max(1,int(width)-2))
                elif isinstance(value,(int,float)) and not isinstance(value,bool):sheet.write_number(ri,ci,value,fmt)
                elif isinstance(value,bool):sheet.write_boolean(ri,ci,value,fmt)
                else:sheet.write_string(ri,ci,_clean(value),fmt)
            sheet.set_row(ri,max(height,min(250,max_lines*14+9)))
        sheet.set_landscape()
        sheet.fit_to_pages(1,0)
        sheet.repeat_rows(0,max(header_rows or [1])-1)
    book.close()
    return stream.getvalue()

MODE = {'air': '空运', 'fcl': '海运整柜', 'lcl': '海运拼箱'}

STATE = {'estimated': '模拟预算', 'simulated': '模拟预估（虚拟参数）', 'partial': '费用待补充', 'invalid': '资料待补充',
         'historical': '历史参考', 'not_applicable': '方案不适用'}

FEE_STATE = {'priced': '已计价', 'missing': '待询价', 'included': '已含',
             'excluded': '不计入', 'not_applicable': '不适用'}

GROUP = {'origin': '起运地', 'freight': '干线', 'destination': '目的地', 'main': '干线'}

BASIS = {'shipment': '票', 'pallet': '板', 'carton': '箱', 'chargeable_kg': '计费kg',
         'container': '柜', 'origin_truck': '提货车', 'destination_truck': '派送车',
         'truck': '车', 'kg': 'kg', 'cbm': 'm³', 'revenue_ton': '计费吨'}

class ExportError(ValueError):
    """A business-readable export failure."""

def _clean(value: Any, default: str = '') -> str:
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        return '是' if value else '否'
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))

def _decimal(value: Any) -> Decimal | None:
    if value is None or value == '' or isinstance(value, bool):
        return None
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None

def _numeric(value: Any, missing: str = '待补充') -> int | float | str:
    n = _decimal(value)
    if n is None:
        return missing
    return int(n) if n == n.to_integral_value() else float(n)

def _format(value: Any, decimals: int = 2, missing: str = '待补充') -> str:
    n = _decimal(value)
    return f'{n:,.{decimals}f}' if n is not None else missing

def _records(value: Any) -> list[dict]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []

def _snapshot(snapshot: dict) -> tuple[dict, dict, list[dict]]:
    if not isinstance(snapshot, dict) or not snapshot.get('id') or not snapshot.get('number'):
        raise ExportError('请先保存测算，再导出文件。')
    req, result = snapshot.get('request'), snapshot.get('result')
    if not isinstance(req, dict) or not isinstance(result, dict):
        raise ExportError('保存快照缺少输入或计算结果。')
    rows = _records(result.get('results'))
    if not rows:
        raise ExportError('当前快照没有可导出的测算方案。')
    return req, result, rows

def _transit(row: dict) -> str:
    t = row.get('transit') or {}
    if isinstance(t, str):
        return t
    lo, hi = t.get('min'), t.get('max')
    if lo is None:
        lo, hi = t.get('min_days'), t.get('max_days')
    if lo is not None and hi is not None:
        return f'{lo}-{hi}自然日'
    return _clean(t.get('label') or t.get('text'), '待货代确认')

def _conditions(row: dict) -> list[str]:
    out = []
    for v in row.get('conditions') or []:
        out.append(_clean(v.get('text') or v.get('message')) if isinstance(v, dict) else _clean(v))
    return [v for v in out if v]

def _status(row: dict) -> str:
    return STATE.get(row.get('status'), '费用待确认')

def _scope(row: dict) -> str:
    return '所选范围预算已齐' if row.get('complete') and row.get('budget_total') is not None else '已知部分，完整总额待补充'

def _fx_text(fx: Any) -> str:
    if not isinstance(fx,dict):return _clean(fx)
    rates=fx.get('rates') or {}
    inverse=fx.get('currency_per_usd') or {}
    target=fx.get('currency','USD')
    parts=[]
    for cur,rate in rates.items():
        if cur==target:continue
        if cur in inverse:parts.append(f'1 {target} = {_clean(inverse[cur])} {cur}')
        else:parts.append(f'1 {cur} = {_clean(rate)} {target}')
    return '；'.join(parts)+('（'+_clean(fx.get('date'))+'预算汇率）' if fx.get('date') else '')

def _catalog(snapshot: dict) -> dict:
    return snapshot.get('catalog_snapshot') or {}

def _saved_time(value: Any) -> str:
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if dt.tzinfo is None:return _clean(value)+'（时区未注明）'
        return dt.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')+'（UTC+08:00）'
    except (ValueError,TypeError):return _clean(value)

def _lookup(catalog: dict, collection: str, key: Any) -> dict:
    return next((r for r in _records(catalog.get(collection)) if r.get('id') == key), {})

def _metadata_rows(snapshot: dict) -> list[list[Any]]:
    req, result, rows = _snapshot(snapshot)
    catalog = _catalog(snapshot)
    product = _lookup(catalog, 'products', req.get('product_id'))
    origin = _lookup(catalog, 'locations', req.get('origin_id'))
    dest = _lookup(catalog, 'locations', req.get('destination_id'))
    return [
        ['测算编号', _clean(snapshot['number'])],
        ['保存时间', _saved_time(snapshot.get('created_at'))],
        ['数据性质', '模拟演示数据，非市场成交价' if result.get('is_demo', True) else '用户维护资料'],
        ['产品', rows[0].get('product_name') or product.get('name') or req.get('product_id')],
        ['数量档位', '、'.join(str(x) for x in req.get('quantities', [])) + '套'],
        ['包装', rows[0].get('packaging_name') or req.get('packaging_id')],
        ['起运点', origin.get('name') or req.get('origin_id')],
        ['目的地', dest.get('name') or req.get('destination_id')],
        ['目的地地址', dest.get('address') or dest.get('display_address') or '按所选服务模板'],
        ['服务范围', '到客户指定地点' if req.get('service_id') == 'door' else '到港／机场场站'],
        ['计划启运日', req.get('departure_date')],
        ['预算币种', result.get('currency', 'USD')],
        ['BU／需求编号', ' / '.join(str((req.get('metadata') or {}).get(k, '')) for k in ('bu', 'reference')).strip(' /')],
        ['资料版本', catalog.get('version') or snapshot.get('catalog_hash') or '快照内版本'],
        ['规则版本', snapshot.get('rule_version') or result.get('engine_version')],
    ]

def export_xlsx(snapshot: dict, preview_dir=None) -> bytes:
    req, result, rows = _snapshot(snapshot)
    number = _clean(snapshot['number'])
    summary = [[], ['内部运费测算单'], ['数据性质', '模拟预算快照；改条件后回工作台重算。']]
    summary += _metadata_rows(snapshot)
    summary += [[], ['数量(套)', '运输方式', '供应商', '预算总额', '预算币种', '每套预算', '费用范围', '参考时效']]
    for r in rows:
        summary.append([r.get('quantity'), MODE.get(r.get('mode'), r.get('mode')),
                        r.get('supplier_name'), _numeric(r.get('budget_total'), '待补齐'),
                        result.get('currency', 'USD'), _numeric(r.get('per_set'), '待补齐'), _scope(r), _transit(r)])
    header = 3 + len(_metadata_rows(snapshot)) + 2

    packaging = [[], ['包装明细'], [f'测算编号：{number}'],
                 ['情景', '交运件类型', '件数', '每件长mm', '每件宽mm', '每件高mm', '每件毛重kg', '计量说明']]
    basis = [[], ['计费依据'], [f'测算编号：{number}'],
             ['情景', '数量(套)', '外箱数', '托盘数', '体积m³', '毛重kg', '材积重kg', '计费重kg', '提货车次', '派送车次', '柜型', '柜数', '费率方案']]
    fees = [[], ['费用明细'], [f'测算编号：{number}；原币金额按保存快照列示'],
            ['情景', '服务段', '费用项目', '计费单位', '计费数量', '单价', '币种', '原币金额', '状态', '来源', '覆盖服务']]
    compare = [[], ['情景对比'], [f'测算编号：{number}'],
               ['数量(套)', '运输方式', '供应商', '包装方案', '原币USD小计', '原币CNY小计', '原币AUD小计', '预算USD', '每套USD', '已知预算USD', '状态', '参考时效']]
    sources = [[], ['来源与待询价项'], [f'测算编号：{number}；预算汇率与资料随本快照固定'],
               ['类型', '情景／编号', '内容', '来源／依据', '备注']]
    for r in rows:
        label = f"{r.get('quantity')}套 {MODE.get(r.get('mode'),r.get('mode'))} {r.get('supplier_name')}"
        s = r.get('shipping') or {}
        units = _records(s.get('handling_units'))
        for u in units:
            dims = u.get('dimensions_mm') or {}
            if isinstance(dims, list):
                dims = dict(zip(('length', 'width', 'height'), dims))
            packaging.append([label, u.get('label') or u.get('type') or u.get('kind') or '交运件',
                              _numeric(u.get('count', u.get('quantity'))),
                              _numeric(u.get('length_mm', dims.get('length'))),
                              _numeric(u.get('width_mm', dims.get('width'))),
                              _numeric(u.get('height_mm', dims.get('height'))),
                              _numeric(u.get('gross_kg', u.get('weight_kg'))),
                              u.get('note') or '按交运外廓计量'])
        if not units:
            packaging.append([label, '交运合计', s.get('pallet_count') or s.get('carton_count'),
                              None, None, None, _numeric(s.get('gross_kg')), '详见计费依据'])
        basis.append([label, r.get('quantity'), s.get('carton_count'), s.get('pallet_count'),
                      _numeric(s.get('volume_m3')), _numeric(s.get('gross_kg')),
                      _numeric(s.get('volumetric_kg')) if r.get('mode')=='air' else '',
                      _numeric(s.get('chargeable_kg')) if r.get('mode')=='air' else '',
                      s.get('origin_trucks'), s.get('destination_trucks'), s.get('container_type') if r.get('mode')=='fcl' else '',
                      s.get('container_count') if r.get('mode')=='fcl' else '', r.get('rate_plan_id')])
        for f in _records(r.get('fees')):
            fees.append([label, GROUP.get(f.get('group'), f.get('group')), f.get('label'),
                         BASIS.get(f.get('basis'), f.get('basis')), _numeric(f.get('quantity')),
                         _numeric(f.get('unit_price'), '待询价'), f.get('currency'),
                         _numeric(f.get('amount'), '待询价'), '模拟补值' if f.get('simulation_origin') else FEE_STATE.get(f.get('state'), f.get('state')),
                         f.get('source_id'), '、'.join(str(x) for x in f.get('covers', []))])
            if f.get('state') == 'missing':
                sources.append(['待询价', label, f.get('label'), f.get('source_id') or '尚未提供', '完整预算待此项补价'])
        original = r.get('original_totals') or {}
        compare.append([r.get('quantity'), MODE.get(r.get('mode'), r.get('mode')), r.get('supplier_name'),
                        r.get('packaging_name'), _numeric(original.get('USD'), ''), _numeric(original.get('CNY'), ''),
                        _numeric(original.get('AUD'), ''), _numeric(r.get('budget_total'), '待补齐'),
                        _numeric(r.get('per_set'), '待补齐'), _numeric(r.get('known_budget'), '待补齐'),
                        _status(r), _transit(r)])
        for msg in _records(r.get('messages')):
            sources.append(['条件', label, msg.get('text') or msg.get('message'), msg.get('code'), msg.get('field')])
        for condition in _conditions(r):
            sources.append(['适用条件', label, condition, r.get('rate_plan_id'), ''])
        fx = r.get('fx') or []
        if isinstance(fx, dict):
            sources.append(['预算汇率', label, _fx_text(fx), req.get('fx_id'), '按原币小计折算，非逐行折算'])
            fx=[]
        for f in _records(fx):
            sources.append(['预算汇率', label, json.dumps(f, ensure_ascii=False), req.get('fx_id'), '按原币小计折算，非逐行折算'])
    catalog = _catalog(snapshot)
    for src in _records(catalog.get('source_documents')):
        sources.append(['资料来源', src.get('id'), src.get('name') or src.get('title') or src.get('description'),
                        src.get('url') or src.get('path') or src.get('kind'), src.get('description') or src.get('note')])
    sources.append(['版本', number, snapshot.get('catalog_hash'), snapshot.get('rule_version') or result.get('engine_version'), '导出不重新计算'])
    sheets = [
        {'name': '询价摘要', 'rows': summary, 'header_rows': [header], 'note_rows': [3], 'widths': [22, 29, 29, 20, 15, 19, 35, 23], 'wrap_columns': [1, 6], 'number_formats':{'0':'#,##0','5':'#,##0.0000'},'preview_rows':28},
        {'name': '包装明细', 'rows': packaging, 'header_rows': [4], 'freeze_rows': 4, 'widths': [40, 20, 12, 16, 16, 16, 18, 28], 'wrap_columns': [0, 7], 'number_formats':{'2':'#,##0','3':'#,##0','4':'#,##0','5':'#,##0','6':'#,##0.000'}},
        {'name': '计费依据', 'rows': basis, 'header_rows': [4], 'freeze_rows': 4, 'widths': [40, 14, 12, 12, 18, 18, 18, 18, 14, 14, 15, 12, 35], 'wrap_columns': [0], 'number_formats':{'1':'#,##0','2':'#,##0','3':'#,##0','4':'#,##0.0000','5':'#,##0.000','6':'#,##0.000','7':'#,##0.000','8':'#,##0','9':'#,##0','11':'#,##0'}},
        {'name': '费用明细', 'rows': fees, 'header_rows': [4], 'freeze_rows': 4, 'widths': [40, 14, 31, 16, 18, 18, 12, 20, 16, 29, 37], 'wrap_columns': [0, 2, 10]},
        {'name': '情景对比', 'rows': compare, 'header_rows': [4], 'freeze_rows': 4, 'widths': [14, 16, 23, 25, 20, 20, 20, 20, 20, 22, 22, 24], 'wrap_columns': [3], 'number_formats':{'0':'#,##0','8':'#,##0.0000'}},
        {'name': '来源与缺项', 'rows': sources, 'header_rows': [4], 'freeze_rows': 4, 'widths': [18, 42, 70, 45, 48], 'wrap_columns': [1, 2, 3, 4]},
    ]
    return workbook_bytes(sheets, preview_dir)

def export_pdf(snapshot: dict, font_bytes: bytes | None = None) -> bytes:
    req, result, rows = _snapshot(snapshot)
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

    font = _font(font_bytes)
    ink, navy, pale = colors.HexColor('#193342'), colors.HexColor('#173F4C'), colors.HexColor('#EDF3F3')
    body = ParagraphStyle('body', fontName=font, fontSize=9, leading=13, textColor=ink, wordWrap='CJK')
    small = ParagraphStyle('small', parent=body, fontSize=8, leading=11)
    title = ParagraphStyle('title', parent=body, fontSize=21, leading=29, spaceAfter=12)
    heading = ParagraphStyle('heading', parent=body, fontSize=13, leading=19, spaceBefore=9, spaceAfter=8)
    white = ParagraphStyle('white', parent=small, textColor=colors.white)
    p = lambda value, style=body: Paragraph(escape(_clean(value)).replace('\n', '<br/>'), style)
    width = A4[0] - 36*mm

    def table(data: list[list[Any]], widths: list[float], header: bool = True):
        converted = [[p(v, white if header and i == 0 else small) for v in row] for i, row in enumerate(data)]
        t = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
        commands = [('FONTNAME', (0,0),(-1,-1),font), ('VALIGN',(0,0),(-1,-1),'TOP'),
                    ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
                    ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
                    ('LINEBELOW',(0,0),(-1,0),.5,colors.HexColor('#D1DEDF'))]
        if header:
            commands += [('BACKGROUND',(0,0),(-1,0),navy),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,pale])]
        t.setStyle(TableStyle(commands))
        return t

    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                                 topMargin=18*mm, bottomMargin=18*mm,
                                 title='内部运费测算单 '+_clean(snapshot['number']), author='运费工作台')
    story = [p('内部运费测算单', title), p(_clean(snapshot['number']) + '    '+_saved_time(snapshot.get('created_at')), small), Spacer(1,8)]
    story += [p('模拟演示资料。用于所选运输范围的内部预算，非货代成交报价。', small), Spacer(1,10)]
    metadata = _metadata_rows(snapshot)
    lead = [[metadata[i][0], metadata[i][1]] for i in (3,4,5,6,7,9,10)]
    story += [table(lead,[83,width-83],False),p('空海运方案比较',heading)]
    summary = [['数量', '运输', '供应商', '总预算 USD', '每套 USD', '参考时效']]
    for r in rows:
        summary.append([str(r.get('quantity'))+'套',MODE.get(r.get('mode'),r.get('mode')),r.get('supplier_name'),
                        _format(r.get('budget_total')), _format(r.get('per_set'),4),_transit(r)])
    story += [table(summary,[43,49,82,100,88,width-362]),Spacer(1,12)]
    for r in rows:
        if r.get('budget_total') is None:
            story.append(p(f"{r.get('quantity')}套{MODE.get(r.get('mode'),r.get('mode'))}：已知预算 USD {_format(r.get('known_budget'))}；完整预算待补齐。",small))
    story += [p('原币费用与预算汇率随本次测算保存。参考时效不代表舱位或订舱承诺。',small)]
    for r in rows:
        story += [PageBreak(),p(f"{r.get('quantity')}套  {MODE.get(r.get('mode'),r.get('mode'))}  {r.get('supplier_name')}",heading)]
        validity=r.get('validity') or {}
        source_line='费率方案：'+_clean(r.get('rate_plan_id'),'尚未匹配')
        if validity.get('valid_from'):
            source_line+='；有效期 '+_clean(validity.get('valid_from'))+' 至 '+_clean(validity.get('valid_until'))
        story += [p(_clean(r.get('route_label')),small),p(_scope(r)+'；'+_status(r),small),p(source_line,small),Spacer(1,8)]
        s=r.get('shipping') or {}
        mode_metric=(['空运材积kg',_format(s.get('volumetric_kg'),0),'空运计费kg',_format(s.get('chargeable_kg'),0)]
                     if r.get('mode')=='air' else ['柜型',s.get('container_type') or '待确认','柜数',s.get('container_count')])
        metric=[['包装与计费','数值','包装与计费','数值'],
                ['外箱数',s.get('carton_count'),'托盘数',s.get('pallet_count')],
                ['交运体积m³',_format(s.get('volume_m3'),4),'总毛重kg',_format(s.get('gross_kg'),1)],
                mode_metric,
                ['提货车次',s.get('origin_trucks'),'派送车次',s.get('destination_trucks')]]
        story += [table(metric,[115,width/2-115,115,width/2-115]),Spacer(1,10)]
        detail=[['费用项目','服务段','计费数量','单价','币种','原币金额']]
        for f in _records(r.get('fees')):
            detail.append([_clean(f.get('label')) + ('〔模拟补值〕' if f.get('simulation_origin') else ''), GROUP.get(f.get('group'),f.get('group')),
                           _format(f.get('quantity'),2)+' '+BASIS.get(f.get('basis'),_clean(f.get('basis'))),
                           _format(f.get('unit_price'),2,'待询价'),f.get('currency'),
                           _format(f.get('amount'),2,FEE_STATE.get(f.get('state'),'待询价'))])
        story += [table(detail,[141,44,87,65,37,width-374]),Spacer(1,9)]
        subtotals = '；'.join(f'{cur} {_format(amount)}' for cur,amount in (r.get('original_totals') or {}).items())
        story += [p('原币小计：'+subtotals,small), p('预算折算 USD '+_format(r.get('budget_total'))+'；每套 USD '+_format(r.get('per_set'),4),body)]
        fx=r.get('fx') or []
        if fx:
            story += [p('预算汇率：'+_fx_text(fx),small)]
        cond = _conditions(r)
        if cond:
            story += [Spacer(1,7),p('范围与条件',body)]
            story += [p(c,small) for c in cond]
        for m in _records(r.get('messages')):
            story.append(p(m.get('text') or m.get('message'),small))
    def footer(canvas, doc):
        canvas.saveState();canvas.setFont(font,7);canvas.setFillColor(colors.HexColor('#5F7781'))
        canvas.drawString(18*mm,10*mm,_clean(snapshot['number'])+'  内部测算  模拟资料')
        canvas.drawRightString(A4[0]-18*mm,10*mm,f'第 {doc.page} 页');canvas.restoreState()
    document.build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()

def export_json(snapshot: dict) -> bytes:
    _snapshot(snapshot)
    return json.dumps(snapshot,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')

def export_inquiry(snapshot: dict) -> bytes:
    req,result,rows=_snapshot(snapshot)
    lines=['运输询价资料与待补充清单',_clean(snapshot['number']),'模拟演示资料；本文件仅生成，未发送给供应商。','']
    lines += [f'{key}：{_clean(value)}' for key,value in _metadata_rows(snapshot)]
    for r in rows:
        s=r.get('shipping') or {}
        mode_basis=(f"计费重：{_format(s.get('chargeable_kg'),0)}kg" if r.get('mode')=='air' else
                    f"柜型／柜数：{s.get('container_type')}／{s.get('container_count')}")
        lines += ['',f"{r.get('quantity')}套 {MODE.get(r.get('mode'),r.get('mode'))} {r.get('supplier_name')}",
                  '路线：'+_clean(r.get('route_label')),
                  f"交运：{s.get('pallet_count')}板，{s.get('carton_count')}箱，{_format(s.get('volume_m3'),4)}m³，{_format(s.get('gross_kg'),1)}kg",
                  mode_basis]
        missing=[f for f in _records(r.get('fees')) if f.get('state')=='missing']
        lines += ['待询价：'+_clean(f.get('label')) for f in missing]
        if not missing:lines.append('当前预置费项已齐。实际承运、舱位、拆票和服务条件请向货代核实。')
        lines += ['需确认：'+c for c in _conditions(r)]
        lines += ['提示：'+_clean(m.get('text') or m.get('message')) for m in _records(r.get('messages'))]
    return ('\n'.join(lines)+'\n').encode('utf-8-sig')
