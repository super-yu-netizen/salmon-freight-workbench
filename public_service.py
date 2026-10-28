"""Stateless public-demo contracts shared by the Worker and CPU-only tests.

No visitor catalog or snapshot is persisted on the server. The browser owns
each workspace; the Worker validates the supplied simulated data for each call.
"""
from copy import deepcopy
import hashlib
import json
from calculator import calculate, _validate_catalog, InputError
from inquiry import read_inquiry_xlsx

MAX_BODY = 4_000_000


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(dumps(value).encode('utf-8')).hexdigest()


def parse_body(raw):
    if not isinstance(raw, str) or not raw or len(raw.encode('utf-8')) > MAX_BODY:
        raise InputError('请求为空或大于4MB，请拆分资料。')
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError):
        raise InputError('请求不是有效JSON，且所有数字必须有限。') from None
    if not isinstance(value, dict):
        raise InputError('请求必须为JSON对象。')
    return value


def checked_catalog(catalog):
    # Public demo limits are deliberately narrower than the desktop importer.
    # They bound repeated validation work without changing any preset choice.
    if not isinstance(catalog, dict):
        raise InputError('缺少模拟资料。')
    plans = catalog.get('rate_plans', [])
    policy = catalog.get('demo_policy', {})
    if not isinstance(plans, list) or not isinstance(policy, dict) or not isinstance(policy.get('reference_plans', []), list):
        raise InputError('费率与演示估价规则的格式不正确。')
    if len(plans) > 120 or len(policy.get('reference_plans', [])) > 120:
        raise InputError('公开演示最多接收120套费率方案；更大的资料请使用本机版本。')
    _validate_catalog(catalog)
    return catalog


def calculate_public(body, seed):
    if not isinstance(body, dict):
        raise InputError('请求必须为JSON对象。')
    catalog = checked_catalog(body.get('catalog', seed))
    request = body.get('request', body)
    result = calculate(request, catalog)
    result.update(catalog_version=catalog['version'], catalog_hash=digest(catalog))
    return result


def validate_public(body):
    catalog = checked_catalog(body.get('catalog'))
    return {'catalog': catalog, 'version': catalog['version'], 'catalog_hash': digest(catalog)}


def checked_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise InputError('请先保存测算，再导出文件。')
    for key in ('id', 'number', 'created_at'):
        if not isinstance(snapshot.get(key), str) or not 0 < len(snapshot[key]) <= 120:
            raise InputError('测算快照的编号或保存时间无效。')
    result = snapshot.get('result')
    if not isinstance(snapshot.get('request'), dict) or not isinstance(result, dict):
        raise InputError('快照缺少输入或结果。')
    rows = result.get('results')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise InputError('一次导出应包含1至32个结果，请拆分数量情景。')
    for row in rows:
        if not isinstance(row, dict) or len(row.get('fees', [])) > 100:
            raise InputError('测算结果格式或费项数量无效。')
        if len(row.get('conditions', [])) > 100 or len(row.get('messages', [])) > 100:
            raise InputError('测算说明过长，请拆分资料。')
    checked_catalog(snapshot.get('catalog_snapshot'))
    # Traversal also bounds pathological nested values before PDF/XLSX layout.
    count = 0
    def visit(value, depth=0):
        nonlocal count
        count += 1
        if count > 150_000 or depth > 25:
            raise InputError('快照结构过大或嵌套过深。')
        if isinstance(value, str) and len(value) > 20_000:
            raise InputError('快照中单项文字过长。')
        if isinstance(value, dict):
            for key, item in value.items():
                visit(key, depth + 1)
                visit(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                visit(item, depth + 1)
    visit(snapshot)
    return snapshot


def import_public(body, seed):
    # Excel imports exact IDs/values; the UI confirms against the visitor catalog.
    checked_catalog(body.get('catalog', seed))
    return read_inquiry_xlsx(body.get('file_base64'))


# Same transparent rule extraction as the desktop server.
def parse_inquiry(text, catalog):
    """A transparent, local shortcut for conventional inquiry text. No LLM claim."""
    import re
    if not isinstance(text, str) or not text.strip() or len(text) > 20000:
        raise ValueError('请粘贴2万字以内的询价文字。')
    draft = {}
    alias_groups = {'MC-001': ['标志碟'], 'Brisbane': ['布里斯班'], 'Singapore': ['新加坡'], 'Rotterdam': ['鹿特丹']}
    for collection, field in [('products', 'product_id'), ('locations', 'destination_id')]:
        for item in catalog.get(collection, []):
            name = item.get('name', '')
            tokens = [item['id'], name, item.get('city', '')] + item.get('aliases', [])
            tokens += alias_groups.get(item['id'], []) + alias_groups.get(item.get('city', ''), [])
            if any(token and token.casefold() in text.casefold() for token in tokens):
                if collection == 'products' or item.get('type', item.get('kind', '')) not in ('origin', 'factory'):
                    draft[field] = item['id']
                    break
    pattern = r'(?<![\d.-])(\d{1,3}(?:,\d{3})+(?!\d)|\d+)'
    line = re.search(r'(?:数量|QTY|Quantity)\s*[:：]\s*([^\n]+)', text, re.I)
    if line:
        number_text = re.split(r'(?:日期|启运|目的|包装|运输|货代|[。])', line.group(1))[0]
        nums = re.findall(pattern, number_text)
    else:
        nums = re.findall(pattern + r'\s*(?:套|sets?|pcs)(?![a-z])', text, re.I)
    vals = []
    for n in nums:
        v = int(n.replace(',', ''))
        if 0 < v <= 1000000 and v not in vals:
            vals.append(v)
    if vals:
        draft['quantities'] = vals[:6]
    date = re.search(r'20\d\d-\d{2}-\d{2}', text)
    if date:
        draft['departure_date'] = date.group()
    modes = []
    if re.search(r'空运|air', text, re.I): modes.append('air')
    if re.search(r'海运|FCL|整柜', text, re.I): modes.append('fcl')
    if modes: draft['modes'] = modes
    return {'draft': draft, 'method': 'local_rules',
            'notes': ['按产品名称、明确数量和日期快捷整理，请确认后再测算。', '没有识别的字段保留现有选择；此入口未调用外部AI。']}
