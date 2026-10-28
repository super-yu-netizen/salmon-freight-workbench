"""Deterministic procurement freight estimates; no HTTP, file writes, or model calls."""
from __future__ import annotations
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, localcontext
import re
from typing import Any

ENGINE_VERSION = '3.1.0'
SCHEMA_VERSION = '3.0.0'
D = Decimal
MONEY = D('.01')
BASES = {'pallet','carton','origin_truck','destination_truck','shipment','chargeable_kg','container','gross_kg','volume_m3'}
COVERAGE_NAMES = {'packing':'包装／打托','origin_pickup':'工厂提货','export_documents':'出口文件／申报','origin_handling':'起运操作','main_freight':'主运费','destination_handling':'目的地操作','destination_documents':'目的地文件','destination_delivery':'末端派送'}

class InputError(ValueError):
    """Safe-to-display invalid input or catalog."""


def decimal(value: Any, label='数值', *, minimum=None, positive=False) -> D:
    if isinstance(value, bool) or value is None or isinstance(value,(dict,list)):
        raise InputError(f'{label}必须是有效数字。')
    if len(str(value))>100:raise InputError(f'{label}数字过长。')
    try:
        n = D(str(value))
    except (InvalidOperation,ValueError,TypeError):
        raise InputError(f'{label}必须是有效数字。') from None
    if not n.is_finite() or abs(n) > D('1e15') or n != 0 and n.adjusted() < -12:
        raise InputError(f'{label}超出允许范围。')
    if positive and n <= 0 or minimum is not None and n < D(str(minimum)):
        raise InputError(f'{label}必须{ "大于0" if positive else "不小于" + str(minimum)}。')
    return n


def integer(value: Any, label='数量', *, minimum=1, maximum=1_000_000) -> int:
    n=decimal(value,label,minimum=minimum)
    if n != n.to_integral_value() or n > maximum:
        raise InputError(f'{label}必须为{minimum}至{maximum}之间的整数。')
    return int(n)


def text(value: Any,label='名称',limit=200) -> str:
    if not isinstance(value,str) or not value.strip() or len(value)>limit:
        raise InputError(f'{label}不能为空，且不超过{limit}字。')
    return value


def stamp(value,label='日期'):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
        raise InputError(f'{label}需使用YYYY-MM-DD。')
    try:return date.fromisoformat(value)
    except ValueError:raise InputError(f'{label}无效。') from None


def number(n: D | int) -> str:
    s=format(D(n),'f')
    return s.rstrip('0').rstrip('.') if '.' in s else s


def money(n: D) -> str:
    return format(n.quantize(MONEY,rounding=ROUND_HALF_UP),'.2f')


def msg(code,text_,field='',severity='warning'):
    return {'code':code,'severity':severity,'text':text_,'field':field}


def _collection(cat,key,limit=500):
    arr=cat.get(key)
    if not isinstance(arr,list) or not arr or len(arr)>limit:
        raise InputError(f'{key}需要非空数组，最多{limit}项。')
    out={}
    for obj in arr:
        if not isinstance(obj,dict):raise InputError(f'{key}含无效条目。')
        ident=text(obj.get('id'),f'{key}.id',100)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',ident):raise InputError(f'{key}标识仅允许字母数字及_.-。')
        if ident in out:raise InputError(f'{key}存在重复标识{ident}。')
        text(obj.get('name'),f'{key}.name')
        out[ident]=obj
    return out


def _validate_catalog(catalog: dict) -> None:
    if not isinstance(catalog,dict):raise InputError('资料源需为JSON对象。')
    text(catalog.get('version'),'资料版本',100)
    if catalog.get('schema_version')!=SCHEMA_VERSION:raise InputError('资料schema_version不兼容，请使用3.0.0模板。')
    if catalog.get('is_demo') is not True:raise InputError('本演示仅接受明确标为is_demo=true的模拟资料。')
    names=('products','packagings','locations','services','load_templates','routes','suppliers','rate_plans','fx','source_documents')
    idx={k:_collection(catalog,k,2000 if k=='rate_plans' else 500) for k in names}
    for key in names:
        for o in idx[key].values():
            if 'source_id' in o and o['source_id'] not in idx['source_documents']:
                raise InputError(f'{key}的来源{str(o["source_id"])}不存在。')
    for source in idx['source_documents'].values():
        if source.get('path') is not None and (not isinstance(source['path'],str) or '/' in source['path'] or '\\' in source['path'] or '..' in source['path'] or len(source['path'])>150):raise InputError('来源文件路径必须是资料目录内的单个文件名。')
        if source.get('url') is not None and (not isinstance(source['url'],str) or not re.match(r'^https?://',source['url'])):raise InputError('来源链接只允许http/https。')
    for p in idx['products'].values():
        text(p.get('unit'),'订单单位',20)
        c=p.get('carton')
        if not isinstance(c,dict):raise InputError('产品需包含外箱资料carton。')
        integer(c.get('units_per_carton'),'每箱数量',maximum=100000)
        for f in ('length_mm','width_mm','height_mm','gross_kg'):
            val=decimal(c.get(f),'外箱'+f,positive=True)
            if val>(D('100000') if f=='gross_kg' else D('20000')):raise InputError('外箱尺寸或毛重超出本版允许范围。')
        if c.get('partial_rule')=='net_plus_tare':
            net=decimal(c.get('unit_net_kg'),'单件净重',minimum=0)
            tare=decimal(c.get('tare_kg'),'尾箱箱重',minimum=0)
            if net*integer(c['units_per_carton'])+tare != decimal(c['gross_kg']):
                raise InputError('净重×装箱量＋箱重需等于外箱毛重，或使用待确认尾箱规则。')
        elif c.get('partial_rule') not in ('unknown','full_carton'):
            raise InputError('尾箱规则需为net_plus_tare、full_carton或unknown。')
        if p.get('default_packaging_id') not in idx['packagings']:raise InputError('产品默认包装不存在。')
    for p in idx['packagings'].values():
        if p.get('product_id') not in idx['products']:raise InputError('包装引用的产品不存在。')
        if p.get('kind') not in ('pallet','carton'):raise InputError('包装形态需为pallet/carton。')
        if not isinstance(p.get('confirmed'),bool):raise InputError('包装确认状态必须为true/false。')
        if p['kind']=='pallet':
            pal=p.get('pallet',{});layout=p.get('layout',{})
            for f in ('length_mm','width_mm','height_mm'):
                if decimal(pal.get(f),'托盘'+f,positive=True)>20000:raise InputError('托盘尺寸超出本版允许范围。')
            for f in ('tare_kg','wrapping_kg'):decimal(pal.get(f),'托盘'+f,minimum=0)
            for f in ('max_height_mm','max_gross_kg'):decimal(p.get(f),f,positive=True)
            integer(p.get('max_layers'),'最多层数',maximum=100)
            for f in ('across_length','across_width'):integer(layout.get(f),'排布'+f,maximum=100)
            if layout.get('carton_length_axis') not in ('length','width'):raise InputError('纸箱朝向必须为length或width。')
            if not isinstance(p.get('allow_overhang'),bool) or not isinstance(p.get('stackable'),bool):raise InputError('悬边与叠放需为true/false。')
        tids=p.get('load_template_ids',{})
        if not isinstance(tids,dict):raise InputError('装载模板引用格式不正确。')
        for v in tids.values():
            if v not in idx['load_templates']:raise InputError('包装的装载模板不存在。')
    for t in idx['load_templates'].values():
        integer(t.get('slots'),'模板托位',maximum=1000)
        if not isinstance(t.get('approved'),bool):raise InputError('模板审核状态需为true/false。')
        for f in ('max_total_kg','max_unit_length_mm','max_unit_width_mm','max_unit_height_mm','max_unit_kg','door_width_mm','door_height_mm','internal_length_mm','internal_width_mm','internal_height_mm'):
            decimal(t.get(f),'模板'+f,positive=True)
        if not isinstance(t.get('packaging_ids'),list) or any(i not in idx['packagings'] for i in t['packaging_ids']):raise InputError('模板适用包装引用无效。')
    for loc in idx['locations'].values():
        if loc.get('kind') not in ('origin','destination'):raise InputError('地点kind需为origin/destination。')
    for route in idx['routes'].values():
        for key,kind in [('origin_id','origin'),('destination_id','destination')]:
            if route.get(key) not in idx['locations'] or idx['locations'][route[key]]['kind']!=kind:raise InputError('路线地点引用无效。')
    for svc in idx['services'].values():
        if not isinstance(svc.get('required_coverage'),list) or not svc['required_coverage'] or any(not isinstance(c,str) for c in svc['required_coverage']):raise InputError('服务模板需列应覆盖项目。')
        if len(set(svc['required_coverage']))!=len(svc['required_coverage']):raise InputError('服务覆盖项目不可重复。')
    for fx in idx['fx'].values():
        stamp(fx.get('date'),'汇率日期');text(fx.get('currency'),'预算币种',3)
        if not isinstance(fx.get('rates'),dict) or not fx['rates']:raise InputError('汇率表为空。')
        for cur,value in fx['rates'].items():
            if not re.fullmatch(r'[A-Z]{3}',cur):raise InputError('币种需为三位大写代码。')
            decimal(value,'汇率',positive=True)
        if decimal(fx['rates'].get(fx['currency']),'预算币汇率')!=1:raise InputError('预算币自身汇率需为1。')
        for cur,value in fx.get('currency_per_usd',{}).items():
            decimal(value,'每美元原币数量',positive=True)
            if cur not in fx['rates']:raise InputError('汇率方向币种没有对应直接汇率。')
            if 'USD' not in fx['rates']:raise InputError('每美元原币汇率需同时提供USD直接汇率。')
            if abs(decimal(value)*decimal(fx['rates'][cur])-decimal(fx['rates']['USD']))>D('1e-20'):raise InputError('汇率的两个方向不一致，请同步更新。')
    natural=[]
    for plan in idx['rate_plans'].values():
        for f,k in [('route_id','routes'),('supplier_id','suppliers'),('origin_id','locations'),('destination_id','locations'),('service_id','services')]:
            if plan.get(f) not in idx[k]:raise InputError(f'费率{plan["id"]}引用{f}不存在。')
        route=idx['routes'][plan['route_id']]
        if any(plan[f]!=route[f] for f in ('origin_id','destination_id')):raise InputError('费率起终点与引用路线不一致。')
        if plan.get('mode') not in ('air','fcl'):raise InputError('费率运输方式需为air/fcl。')
        start=stamp(plan.get('valid_from'),'费率生效日');end=stamp(plan.get('valid_until'),'费率失效日')
        if start>end:raise InputError('费率生效日不能晚于失效日。')
        if plan.get('validity_basis')!='departure_date':raise InputError('本版费率有效性基准需为departure_date。')
        for f,k in [('product_ids','products'),('packaging_ids','packagings')]:
            if not isinstance(plan.get(f),list) or not plan[f] or any(x not in idx[k] for x in plan[f]):raise InputError('费率产品/包装适用引用无效。')
        if plan['mode']=='air':
            a=plan.get('air_rules',{})
            decimal(a.get('divisor_cm3'),'体积重除数',positive=True);decimal(a.get('round_kg'),'进位公斤',positive=True)
            mi=decimal(a.get('min_kg'),'最低计费重量',minimum=0);ma=decimal(a.get('max_kg'),'最大计费重量',positive=True)
            if ma<mi:raise InputError('空运重量适用区间不正确。')
            if a.get('scope') not in ('shipment','piece'):raise InputError('空运计算范围需为shipment/piece。')
            if a.get('allow_breakback') is not False:raise InputError('本版不启用未经确认的重量靠级，请设allow_breakback=false。')
        fees=plan.get('fees')
        if not isinstance(fees,list) or not fees or len(fees)>100:raise InputError('费率需包含1至100项费用。')
        fids=set()
        for fee in fees:
            if not isinstance(fee,dict):raise InputError('费用行需为对象。')
            fid=text(fee.get('id'),'费用ID',100)
            if fid in fids:raise InputError('同费率的费用ID不能重复。')
            fids.add(fid);text(fee.get('label'),'费用名称')
            if fee.get('group') not in ('origin','freight','destination','other'):raise InputError('费用分组无效。')
            if fee.get('basis') not in BASES:raise InputError('费用计费单位不受本版支持。')
            if fee.get('state') not in ('priced','missing','included','excluded'):raise InputError('费用状态无效。')
            if not re.fullmatch(r'[A-Z]{3}',str(fee.get('currency',''))):raise InputError('费用币种无效。')
            if fee.get('unit_price') is not None:decimal(fee['unit_price'],'费用单价',minimum=0)
            for fld in ('minimum_amount','maximum_amount','minimum_quantity'):
                if fee.get(fld) is not None:decimal(fee[fld],fld,minimum=0)
            if fee.get('minimum_amount') is not None and fee.get('maximum_amount') is not None and decimal(fee['maximum_amount'])<decimal(fee['minimum_amount']):raise InputError('费用上限不能低于最低收费。')
            if not isinstance(fee.get('covers'),list) or any(not isinstance(c,str) for c in fee['covers']):raise InputError('费用需列覆盖服务项目。')
            if fee.get('source_id') not in idx['source_documents']:raise InputError('费用来源不存在。')
            previous_end=None
            for j,tier in enumerate(fee.get('tiers',[])):
                lo=decimal(tier.get('min'),'档位下限',minimum=0);hi=decimal(tier['max'],'档位上限',positive=True) if tier.get('max') is not None else None
                decimal(tier.get('unit_price'),'档位单价',minimum=0)
                if hi is not None and hi<=lo:raise InputError('档位上下限无效。')
                if j and (previous_end is None or lo<previous_end):raise InputError('重量档位重叠或顺序无效。')
                previous_end=hi
        for f in fees:
            if f['state']=='included' and (f.get('included_in') not in fids or f['included_in']==f['id']):raise InputError('已含费用需引用另一有效费用包。')
        key=(plan['supplier_id'],plan['route_id'],plan['mode'],plan['service_id'])
        for other in natural:
            if key==other[0] and start<=other[2] and end>=other[1] and set(plan['product_ids'])&other[3] and set(plan['packaging_ids'])&other[4]:raise InputError('相同条件存在重叠费率，请区分适用期或范围。')
        natural.append((key,start,end,set(plan['product_ids']),set(plan['packaging_ids'])))
    for prod in idx['products'].values():
        if idx['packagings'][prod['default_packaging_id']]['product_id']!=prod['id']:raise InputError('默认包装与产品不匹配。')
    # Validate default references without calculating, so imported catalogs stay self-contained.
    req=catalog.get('default_request')
    if not isinstance(req,dict):raise InputError('需提供default_request。')
    _request(req,idx)
    policy = catalog.get('demo_policy')
    if policy is not None:
        if not isinstance(policy, dict) or not isinstance(policy.get('enabled'), bool):
            raise InputError('演示估价规则格式不正确。')
        if policy.get('source_id') not in idx['source_documents']:
            raise InputError('演示估价规则来源不存在。')
        stamp(policy.get('reference_date'), '演示估价基准日')
        multiplier = decimal(policy.get('project_main_multiplier'), '项目货模拟系数', minimum=1)
        if multiplier > 5:raise InputError('项目货模拟系数超出允许范围。')
        reference_catalog = dict(catalog)
        reference_catalog.pop('demo_policy', None)
        reference_catalog['rate_plans'] = policy.get('reference_plans')
        reference_catalog['fx'] = policy.get('reference_fx')
        _validate_catalog(reference_catalog)


def validate_catalog(catalog: dict) -> None:
    try:
        _validate_catalog(catalog)
    except InputError:
        raise
    except (TypeError,KeyError,AttributeError,IndexError,InvalidOperation) as exc:
        raise InputError('资料源结构或字段类型不正确，请使用完整资料模板。') from exc


def _request(req,idx):
    if not isinstance(req,dict):raise InputError('测算请求需为对象。')
    if 'demo_estimation' in req and not isinstance(req['demo_estimation'], bool):raise InputError('演示估价开关需为true/false。')
    for f,k in [('product_id','products'),('packaging_id','packagings'),('origin_id','locations'),('destination_id','locations'),('service_id','services'),('fx_id','fx')]:
        if not isinstance(req.get(f),str) or req.get(f) not in idx[k]:raise InputError(f'请选择有效的{f}。')
    if idx['locations'][req['origin_id']]['kind']!='origin' or idx['locations'][req['destination_id']]['kind']!='destination':raise InputError('起运地/目的地类型不正确。')
    if idx['packagings'][req['packaging_id']]['product_id']!=req['product_id']:raise InputError('包装版本与产品不匹配。')
    qs=req.get('quantities')
    if not isinstance(qs,list) or not 1<=len(qs)<=8:raise InputError('请填写1至8档数量。')
    for q in qs:integer(q,'订单数量')
    if len(set(integer(q,'订单数量') for q in qs))!=len(qs):raise InputError('数量档位请勿重复。')
    modes=req.get('modes')
    if not isinstance(modes,list) or not modes or any(m not in ('air','fcl') for m in modes) or len(set(modes))!=len(modes):raise InputError('请选择空运或海运整柜。')
    supp=req.get('supplier_ids')
    if not isinstance(supp,list) or not 1<=len(supp)<=10 or any(not isinstance(s,str) or s not in idx['suppliers'] for s in supp) or len(set(supp))!=len(supp):raise InputError('请选择有效且不重复的货代方案。')
    stamp(req.get('departure_date'),'计划启运日期')
    if not isinstance(req.get('metadata',{}),dict):raise InputError('metadata需为对象。')
    overrides=req.get('fee_overrides',{})
    if not isinstance(overrides,dict):raise InputError('费用补充格式不正确。')
    for pid,fees in overrides.items():
        if pid not in idx['rate_plans'] or not isinstance(fees,dict):raise InputError('费用补充引用无效费率。')
        validids={f['id'] for f in idx['rate_plans'][pid]['fees']}
        for fid,v in fees.items():
            if fid not in validids:raise InputError('费用补充引用无效费用行。')
            if v is not None:decimal(v,'本次费用单价',minimum=0)
    if not isinstance(req.get('load_counts',{}),dict):raise InputError('人工装载数量需为对象。')
    for k,v in req.get('load_counts',{}).items():
        if k not in ('origin_trucks','destination_trucks','container_count'):raise InputError('人工装载数量字段无效。')
        integer(v,'人工装载数量',maximum=100000)


def _unit(label,count,cartons,l,w,h,gross,kind):
    return {'label':label,'kind':kind,'count':count,'cartons_per_unit':cartons,'length_mm':number(l),'width_mm':number(w),'height_mm':number(h),'gross_kg':number(gross),'volume_m3':number(l*w*h/D(10**9))}


def _shipping(q,prod,pack,loads,req):
    c=prod['carton'];per=integer(c['units_per_carton']);fullcartons,remainder=divmod(q,per)
    boxes=fullcartons+bool(remainder);boxgross=decimal(c['gross_kg']);l,w,h=(decimal(c[x]) for x in ('length_mm','width_mm','height_mm'))
    tailgross=None
    if remainder:
        if c.get('partial_rule')=='net_plus_tare':tailgross=decimal(c['unit_net_kg'])*remainder+decimal(c['tare_kg'])
        elif c.get('partial_rule')=='full_carton':tailgross=boxgross
        else:raise InputError('本次数量产生尾箱，请补充尾箱实际毛重或采用已审核尾箱规则。')
    cargo_gross=D(fullcartons)*boxgross+(tailgross or 0)
    units=[];messages=[];load_details=[]
    if pack.get('confirmed') is not True:raise InputError('所选包装版本尚未确认，请先补充有效包装。')
    if pack['kind']=='carton':
        if fullcartons:units.append(_unit('满箱',fullcartons,1,l,w,h,boxgross,'carton'))
        if remainder:units.append(_unit('尾箱',1,1,l,w,h,tailgross,'carton'))
        pallet_count=0;full_pallets=0;tail_cartons=0;layers=0
    else:
        p=pack['pallet'];pl,pw,ph=(decimal(p[x]) for x in ('length_mm','width_mm','height_mm'))
        pt=decimal(p['tare_kg'])+decimal(p['wrapping_kg'])
        layout=pack['layout'];ax=integer(layout['across_length']);ay=integer(layout['across_width']);on_layer=ax*ay
        dx,dy=(l,w) if layout['carton_length_axis']=='length' else (w,l)
        if not pack.get('allow_overhang') and (dx*ax>pl or dy*ay>pw):raise InputError('所选每层排布超出托盘底面，请调整包装方案。')
        outer_length=max(pl,dx*ax);outer_width=max(pw,dy*ay)
        height_layers=int(((decimal(pack['max_height_mm'])-ph)/h).to_integral_value(rounding=ROUND_FLOOR))
        weight_cartons=int(((decimal(pack['max_gross_kg'])-pt)/boxgross).to_integral_value(rounding=ROUND_FLOOR))
        weight_layers=weight_cartons//on_layer
        layers=min(integer(pack['max_layers']),height_layers,weight_layers)
        if layers<1:raise InputError('托盘限高或限重不足以装一层货物。')
        cap=on_layer*layers
        standard_full,remaining_full_boxes=divmod(fullcartons,cap)
        if standard_full:units.append(_unit('满托',standard_full,cap,outer_length,outer_width,ph+layers*h,D(cap)*boxgross+pt,'pallet'))
        last_boxes=remaining_full_boxes+bool(remainder)
        if last_boxes:
            last_layers=(last_boxes+on_layer-1)//on_layer
            lastgross=D(remaining_full_boxes)*boxgross+(tailgross or 0)+pt
            occupied_per_layer=min(last_boxes,on_layer)
            last_length=max(pl,dx*min(ax,occupied_per_layer))
            last_width=max(pw,dy*((occupied_per_layer+ax-1)//ax))
            units.append(_unit('尾托' if last_boxes<cap else '含尾箱的满托',1,last_boxes,last_length,last_width,ph+last_layers*h,lastgross,'pallet'))
        pallet_count=sum(u['count'] for u in units)
        full_pallets=boxes//cap;tail_cartons=boxes%cap
    volume=sum((decimal(u['volume_m3'])*u['count'] for u in units),D(0))
    gross=sum((decimal(u['gross_kg'])*u['count'] for u in units),D(0))
    sh={'carton_count':boxes,'full_carton_count':fullcartons,'tail_carton_units':remainder,'pallet_count':pallet_count,'full_pallets':full_pallets,'tail_cartons':tail_cartons,'layers_per_full_pallet':layers,'volume_m3':number(volume),'gross_kg':number(gross),'cargo_gross_kg':number(cargo_gross),'volumetric_kg':None,'chargeable_kg':None,'origin_trucks':None,'destination_trucks':None,'container_count':None,'container_type':'40HQ','handling_units':units,'load_plans':load_details}
    for kind,field in [('origin','origin_trucks'),('fcl','container_count'),('destination','destination_trucks')]:
        if req.get('load_counts',{}).get(field) is not None:
            sh[field]=integer(req['load_counts'][field]);load_details.append({'kind':kind,'method':'manual','count':sh[field],'note':'本次人工确认的装载数量；需以实际装载依据为准。'});continue
        tid=pack.get('load_template_ids',{}).get(kind);t=loads.get(tid)
        if not t or t.get('approved') is not True or pack['id'] not in t.get('packaging_ids',[]) or not pallet_count:
            load_details.append({'kind':kind,'template_id':tid,'count':None,'note':'缺少适用的已审核装载模板。'});continue
        failures=[]
        for u in units:
            for uf,tf in [('length_mm','max_unit_length_mm'),('width_mm','max_unit_width_mm'),('height_mm','max_unit_height_mm'),('gross_kg','max_unit_kg')]:
                if decimal(u[uf])>decimal(t[tf]):failures.append('交运件超出模板'+tf)
            if decimal(u['width_mm'])>decimal(t['door_width_mm']) or decimal(u['height_mm'])>decimal(t['door_height_mm']):failures.append('交运件超出设备门尺寸')
            if any(decimal(u[f])>decimal(t[g]) for f,g in [('length_mm','internal_length_mm'),('width_mm','internal_width_mm'),('height_mm','internal_height_mm')]):failures.append('交运件超出设备内尺寸')
        max_unit_weight=max(decimal(u['gross_kg']) for u in units)
        weight_slots=int((decimal(t['max_total_kg'])/max_unit_weight).to_integral_value(rounding=ROUND_FLOOR))
        capacity=min(integer(t['slots']),weight_slots)
        if capacity<1:failures.append('设备载重不足')
        if failures:
            load_details.append({'kind':kind,'template_id':tid,'count':None,'note':'；'.join(sorted(set(failures)))});continue
        n=(pallet_count+capacity-1)//capacity
        sh[field]=n
        if kind=='fcl':sh['container_type']=t.get('container_type') or '40HQ'
        load_details.append({'kind':kind,'template_id':tid,'name':t['name'],'count':n,'slots':capacity,'is_demo':True,'note':t.get('note','')})
    return sh


def _chargeable(sh,rules):
    divisor=decimal(rules['divisor_cm3']);step=decimal(rules['round_kg'])
    vol=decimal(sh['volume_m3'])*D(1000000)/divisor
    def ceilstep(x):return (x/step).to_integral_value(rounding=ROUND_CEILING)*step
    if rules['scope']=='piece':
        cw=sum((ceilstep(max(decimal(u['gross_kg']),decimal(u['volume_m3'])*1000000/divisor))*u['count'] for u in sh['handling_units']),D(0))
    else:cw=ceilstep(max(decimal(sh['gross_kg']),vol))
    cw=ceilstep(max(cw,decimal(rules.get('min_kg','0'))))
    sh['volumetric_kg']=number(vol);sh['chargeable_kg']=number(cw)
    sh['air_calculation']={'scope':rules['scope'],'divisor_cm3':number(divisor),'round_kg':number(step),'formula':'交运外廓cm³÷材积除数；按约定范围取毛重/材积重较大者后进位。'}
    return cw


def _base_result(q,mode,supplier,prod,pack,req,fx):
    return {'id':f'{q}-{mode}-{supplier["id"]}-{pack["id"]}','quantity':q,'mode':mode,'supplier_id':supplier['id'],'supplier_name':supplier['name'],'product_id':prod['id'],'product_name':prod['name'],'product_unit':prod['unit'],'packaging_id':pack['id'],'packaging_name':pack['name'],'route_label':'','status':'not_applicable','complete':False,'messages':[],'shipping':{},'fees':[],'original_totals':{},'budget_total':None,'known_budget':None,'per_set':None,'known_per_set':None,'currency':fx['currency'],'fx':deepcopy(fx),'transit':None,'conditions':[],'coverage':{'required':[],'covered':[],'missing':[]},'rate_plan_id':None,'is_demo':True}


def _quantity(basis,sh):
    key={'pallet':'pallet_count','carton':'carton_count','origin_truck':'origin_trucks','destination_truck':'destination_trucks','chargeable_kg':'chargeable_kg','container':'container_count','gross_kg':'gross_kg','volume_m3':'volume_m3'}.get(basis)
    if basis=='shipment':return D(1)
    raw=sh.get(key)
    return None if raw is None else decimal(raw)


def _budget(totals,fx):
    sums=[];missing=[]
    for cur,amt in sorted(totals.items()):
        if cur not in fx['rates']:missing.append(cur);continue
        if fx['currency']=='USD' and cur in fx.get('currency_per_usd',{}):value=amt/decimal(fx['currency_per_usd'][cur])
        else:value=amt*decimal(fx['rates'][cur])
        sums.append(value.quantize(MONEY,rounding=ROUND_HALF_UP))
    return sum(sums,D(0)) if not missing else None,missing


def _fees(plan,sh,req,svc):
    lines=[];messages=[];totals={};covered=set();owners={};pending=[]
    overrides=req.get('fee_overrides',{}).get(plan['id'],{})
    for raw in plan['fees']:
        f=deepcopy(raw);fid=f['id'];state=f['state'];qty=_quantity(f['basis'],sh);price=f.get('unit_price');amount=None
        if fid in overrides:price=overrides[fid];state='missing' if price is None else 'priced'
        # Included rows are resolved after priced parent rows have actually succeeded.
        if state=='priced':
            if f.get('tiers') and fid not in overrides and qty is not None:
                match=[t for t in f['tiers'] if qty>=decimal(t['min']) and (t.get('max') is None or qty<decimal(t['max']))]
                price=match[0]['unit_price'] if len(match)==1 else None
            if qty is None or price is None:state='missing'
            else:
                duplicate=[c for c in f['covers'] if c in owners]
                if duplicate:
                    state='missing';messages.append(msg('DUPLICATE_COVERAGE',f'{f["label"]}与另一费用重复覆盖{",".join(duplicate)}，请核对包含关系。',fid))
                else:
                    used_qty=max(qty,decimal(f.get('minimum_quantity','0')))
                    amount=used_qty*decimal(price)
                    if f.get('minimum_amount') is not None:amount=max(amount,decimal(f['minimum_amount']))
                    if f.get('maximum_amount') is not None:amount=min(amount,decimal(f['maximum_amount']))
                    amount=amount.quantize(MONEY,rounding=ROUND_HALF_UP)
                    totals[f['currency']]=totals.get(f['currency'],D(0))+amount
                    covered.update(f['covers'])
                    for c in f['covers']:owners[c]=fid
                    f['billing_quantity']=number(used_qty)
        if state=='missing':
            pending.append(fid);messages.append(msg('FEE_MISSING',f'{f["label"]}待询价或缺少计费数量。',fid))
        f.update({'quantity':number(qty) if qty is not None else None,'unit_price':number(decimal(price)) if price is not None else None,'amount':money(amount) if amount is not None else None,'state':state})
        lines.append(f)
    byid={f['id']:f for f in lines}
    def included_parent_priced(fid,visited):
        if fid in visited:return False
        f=byid.get(fid)
        if not f:return False
        if f['state']=='priced':return f['amount'] is not None
        if f['state']=='included':return included_parent_priced(f.get('included_in'),visited|{fid})
        return False
    for f in lines:
        if f['state']=='included':
            if included_parent_priced(f.get('included_in'),{f['id']}):covered.update(f['covers'])
            else:
                f['state']='missing';pending.append(f['id'])
                messages.append(msg('INCLUDED_PARENT_MISSING',f'{f["label"]}的费用包尚未计价。',f['id']))
    missing=[c for c in svc['required_coverage'] if c not in covered]
    for c in missing:
        if not any(c in f['covers'] and f['state']=='missing' for f in lines):
            lines.append({'id':'coverage-'+c,'group':'other','label':COVERAGE_NAMES.get(c,c)+'（待询价）','basis':'shipment','quantity':'1','unit_price':None,'currency':'USD','amount':None,'state':'missing','source_id':svc.get('source_id'),'covers':[c]})
        messages.append(msg('COVERAGE_MISSING',f'所选范围尚缺{COVERAGE_NAMES.get(c,c)}。',c))
    return lines,totals,messages,{'required':svc['required_coverage'],'covered':sorted(covered),'missing':missing}, bool(pending or missing)


def calculate_strict(request: dict,catalog: dict) -> dict:
    """Calculate a matrix of frozen-source procurement estimates using Decimal."""
    validate_catalog(catalog)
    idx={k:{o['id']:o for o in catalog[k]} for k in ('products','packagings','locations','services','load_templates','routes','suppliers','rate_plans','fx')}
    _request(request,idx)
    req=deepcopy(request);prod=idx['products'][req['product_id']];pack=idx['packagings'][req['packaging_id']];fx=idx['fx'][req['fx_id']];svc=idx['services'][req['service_id']]
    results=[]
    with localcontext() as ctx:
        ctx.prec=40
        for rawq in req['quantities']:
            q=integer(rawq,'订单数量')
            try:physical=_shipping(q,prod,pack,idx['load_templates'],req);physical_error=None
            except InputError as e:physical={};physical_error=str(e)
            for mode in req['modes']:
                for sid in req['supplier_ids']:
                    r=_base_result(q,mode,idx['suppliers'][sid],prod,pack,req,fx);r['shipping']=deepcopy(physical)
                    if physical_error:
                        r['status']='invalid';r['messages'].append(msg('PACKAGING_INVALID',physical_error,'packaging_id','error'));results.append(r);continue
                    matches=[p for p in catalog['rate_plans'] if p['mode']==mode and p['supplier_id']==sid and p['origin_id']==req['origin_id'] and p['destination_id']==req['destination_id'] and p['service_id']==req['service_id'] and prod['id'] in p['product_ids'] and pack['id'] in p['packaging_ids']]
                    if not matches:
                        r['messages'].append(msg('RATE_NOT_FOUND','所选地点、运输方式和服务范围暂无适用费率；已保留货量，可生成询价清单。','rate_plan_id'));results.append(r);continue
                    departure=stamp(req['departure_date']);valid=[p for p in matches if stamp(p['valid_from'])<=departure<=stamp(p['valid_until'])]
                    plan=sorted(valid or matches,key=lambda p:p['valid_from'],reverse=True)[0]
                    r['rate_plan_id']=plan['id'];route=idx['routes'][plan['route_id']];r['route_label']=route['name']+' · '+svc['name'];r['transit']=deepcopy(plan.get('transit'));r['conditions']=list(dict.fromkeys(plan.get('conditions',[])+svc.get('excluded',[])))
                    r['validity']={'valid_from':plan['valid_from'],'valid_until':plan['valid_until'],'basis':'departure_date','departure_date':req['departure_date'],'matched':bool(valid)}
                    if mode=='air':
                        cw=_chargeable(r['shipping'],plan['air_rules'])
                        if cw>decimal(plan['air_rules']['max_kg']):
                            r['status']='not_applicable';r['messages'].append(msg('WEIGHT_OUT_OF_SCOPE','本次计费重量超出费率适用上限，请另询项目货运价。','quantities'));results.append(r);continue
                    lines,totals,notes,coverage,partial=_fees(plan,r['shipping'],req,svc)
                    r['fees']=lines;r['original_totals']={k:money(v) for k,v in sorted(totals.items())};r['messages'].extend(notes);r['coverage']=coverage
                    value,missing_fx=_budget(totals,fx)
                    if missing_fx:r['messages'].append(msg('FX_MISSING','缺少'+','.join(missing_fx)+'预算汇率，原币小计已保留。','fx_id'));partial=True
                    r['known_budget']=money(value) if value is not None and totals else None
                    r['known_per_set']=format((value/D(q)).quantize(D('.0001'),rounding=ROUND_HALF_UP),'.4f') if value is not None and totals else None
                    if not valid:
                        r['status']='historical';r['messages'].append(msg('RATE_EXPIRED','启运日期不在费率有效期，仅保留历史参考小计，请更新费率。','departure_date'))
                    elif partial:r['status']='partial'
                    else:
                        r['status']='estimated';r['complete']=True;r['budget_total']=r['known_budget'];r['per_set']=r['known_per_set']
                    results.append(r)
    return {'schema_version':SCHEMA_VERSION,'engine_version':ENGINE_VERSION,'is_demo':True,'currency':fx['currency'],'request':req,'results':results,'messages':[]}


def calculate(request: dict, catalog: dict) -> dict:
    result = calculate_strict(request, catalog)
    if request.get('demo_estimation') is True:
        from demo_estimation import apply_demo_estimation
        result = apply_demo_estimation(request, catalog, calculate_strict, result)
    return result
