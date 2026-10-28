"""Explicit demo-only estimates, with frozen virtual baselines and provenance.

The strict calculator remains the source of arithmetic. This adapter only makes
stated demo assumptions and never writes them back to supplier rates or inputs.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal


def _matching(plans, request, row):
    return [p for p in plans if p['mode'] == row['mode']
            and p['supplier_id'] == row['supplier_id']
            and p['origin_id'] == request['origin_id']
            and p['destination_id'] == request['destination_id']
            and p['service_id'] == request['service_id']
            and request['product_id'] in p['product_ids']
            and request['packaging_id'] in p['packaging_ids']]


def apply_demo_estimation(request, catalog, strict_calculate, result):
    policy = catalog.get('demo_policy', {})
    if request.get('demo_estimation') is not True or catalog.get('is_demo') is not True or policy.get('enabled') is not True:
        return result
    source_id = policy['source_id']
    references = policy['reference_plans']
    active = {p['id']: p for p in catalog['rate_plans']}
    for index, original in enumerate(result['results']):
        if original['budget_total'] is not None or original['status'] == 'invalid':
            continue
        choices = _matching(references, request, original)
        if not choices:
            continue  # No invented prices for unknown services or foreign data.
        reference = choices[0]
        supplied = active.get(original.get('rate_plan_id'))
        plan = deepcopy(supplied or reference)
        reasons, adjustments = [], []
        original_validity = deepcopy(original.get('validity'))
        departure = date.fromisoformat(request['departure_date'])
        if not supplied:
            reasons.append('该组合采用预置的独立模拟费率模板。')
        if not (date.fromisoformat(plan['valid_from']) <= departure <= date.fromisoformat(plan['valid_until'])):
            reasons.append('启运日不在原费率期限内，按演示基准估算，不代表该日期市场报价。')
        # Temporary calculation scope only; original dates are retained below.
        plan['valid_from'] = plan['valid_until'] = request['departure_date']
        reference_fees = {f['id']: f for f in reference['fees']}
        overrides = request.get('fee_overrides', {}).get(plan['id'], {})
        represented = {f['id'] for f in plan['fees']}
        required = set(next(s for s in catalog['services'] if s['id'] == request['service_id'])['required_coverage'])
        covered = {c for f in plan['fees'] for c in f['covers']}
        for f in reference['fees']:
            if f['id'] not in represented and set(f['covers']) & (required - covered):
                added = deepcopy(f)
                added.update(simulation_origin=source_id, source_id=source_id, original_unit_price=None)
                plan['fees'].append(added)
                covered.update(f['covers'])
                reasons.append(f'缺少的“{f["label"]}”采用模拟模板补值。')
                adjustments.append({'fee_id': f['id'], 'original_unit_price': None,
                                    'estimated_unit_price': f['unit_price'], 'currency': f['currency']})
        for i, fee in enumerate(plan['fees']):
            ref = reference_fees.get(fee['id'])
            overridden_missing = fee['id'] in overrides and overrides[fee['id']] is None
            if ref and (overridden_missing or fee['state'] == 'missing'
                        or fee['state'] == 'priced' and fee.get('unit_price') is None):
                virtual = deepcopy(ref)
                virtual.update(simulation_origin=source_id, source_id=source_id,
                               original_unit_price=None if overridden_missing else fee.get('unit_price'),
                               original_currency=fee['currency'])
                plan['fees'][i] = virtual
                reasons.append(f'“{fee["label"]}”未获价，采用模拟模板{ref["currency"]} {ref["unit_price"]}／约定单位。')
                adjustments.append({'fee_id': fee['id'], 'original_unit_price': virtual['original_unit_price'],
                                    'estimated_unit_price': ref['unit_price'], 'currency': ref['currency']})
        codes = {m['code'] for m in original['messages']}
        if original['mode'] == 'air' and 'WEIGHT_OUT_OF_SCOPE' in codes:
            multiplier = Decimal(policy['project_main_multiplier'])
            plan['air_rules']['max_kg'] = '1000000000000000'
            main = next((f for f in plan['fees'] if f['id'] == 'main'), None)
            if main:
                before = overrides.get(main['id'], main.get('unit_price'))
                if before is not None:
                    main['unit_price'] = format(Decimal(str(before)) * multiplier, 'f')
                    main.pop('tiers', None)
                    main.update(simulation_origin=source_id, source_id=source_id, original_unit_price=before)
                    adjustments.append({'fee_id': main['id'], 'original_unit_price': before,
                                        'estimated_unit_price': main['unit_price'], 'currency': main['currency']})
                    reasons.append(f'大货超过基准重量范围，主运费按基准单价×{multiplier}作项目货模拟；不承诺实际舱位。')
        temporary = deepcopy(catalog)
        temporary['rate_plans'] = [plan]
        fx = next(f for f in temporary['fx'] if f['id'] == request['fx_id'])
        reference_fx = next((f for f in policy.get('reference_fx', []) if f['id'] == fx['id']), None)
        if reference_fx:
            used_currencies = {f['currency'] for f in plan['fees'] if f['state'] == 'priced'}
            for currency in used_currencies:
                if currency not in fx['rates'] and currency in reference_fx['rates']:
                    fx['rates'][currency] = reference_fx['rates'][currency]
                    if currency in reference_fx.get('currency_per_usd', {}):
                        fx.setdefault('currency_per_usd', {})[currency] = reference_fx['currency_per_usd'][currency]
                    reasons.append(f'{currency}缺少预算汇率，采用模拟基准汇率。')
        trial_request = deepcopy(request)
        trial_request.update(quantities=[original['quantity']], modes=[original['mode']],
                             supplier_ids=[original['supplier_id']], demo_estimation=False)
        # Explicit quoted overrides remain; only unresolved values use the
        # estimated fees above, while the saved original request retains nulls.
        changed = {a['fee_id'] for a in adjustments}
        trial_request['fee_overrides'] = {plan['id']: {fid: value for fid, value in overrides.items()
                                                      if value is not None and fid not in changed}}
        calculated = strict_calculate(trial_request, temporary)['results'][0]
        if calculated['budget_total'] is None:
            continue  # Invalid packaging, duplicate coverage or unknown rules stay visible.
        calculated['status'] = 'simulated'
        calculated['complete'] = True
        calculated['validity'] = original_validity or {'matched': False, 'basis': 'demo_reference',
                                                      'departure_date': request['departure_date']}
        calculated['estimate'] = {
            'applied': True, 'source_id': source_id, 'reference_date': policy['reference_date'],
            'reference_plan_id': reference['id'], 'base_rate_plan_id': supplied['id'] if supplied else None,
            'original_status': original['status'], 'original_validity': original_validity,
            'original_messages': deepcopy(original['messages']), 'reasons': list(dict.fromkeys(reasons)),
            'adjustments': adjustments,
        }
        if not calculated['estimate']['reasons']:
            calculated['estimate']['reasons'] = ['按已配置的模拟费率模板生成演示参考预算。']
        calculated['pricing_basis'] = '演示模拟估价，非供应商正式报价'
        calculated['messages'] = [{'code': 'DEMO_ESTIMATE', 'severity': 'info', 'field': 'demo_estimation', 'text': x}
                                  for x in calculated['estimate']['reasons']]
        calculated['conditions'] = ['演示模拟估价：缺项／超期／项目货条件采用明确的虚拟假设。'] + calculated['estimate']['reasons'] + calculated['conditions']
        result['results'][index] = calculated
    return result
