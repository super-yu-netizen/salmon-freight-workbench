/* Public demo storage adapter. Business arithmetic stays in the Python Worker.
 * Catalog edits and immutable estimates belong to this browser, never to a
 * shared public workspace. The localhost desktop server keeps its own API.
 */
(function () {
  'use strict';
  const loopback = ['localhost', '127.0.0.1', '::1', '[::1]'].includes(location.hostname);
  const enabled = window.FREIGHT_PUBLIC_MODE === true || new URLSearchParams(location.search).get('public_demo') === '1' || !loopback;
  const KEY = 'salmon-freight-workspace:v1';
  const LOCK = 'salmon-freight-workspace:write';
  const copy = value => JSON.parse(JSON.stringify(value));
  const isObject = value => value && typeof value === 'object' && !Array.isArray(value);
  let serial = Promise.resolve();

  async function remote(path, options = {}) {
    const response = await fetch(path, {cache: 'no-store', ...options, headers: {'Content-Type': 'application/json', ...options.headers}});
    let body;
    try { body = await response.json(); } catch { throw new Error('服务返回的数据格式有误，请稍后重试。'); }
    if (!response.ok) throw new Error(body.error || body.message || '请求未能完成，请稍后重试。');
    return body;
  }
  const remotePost = (path, body) => remote(path, {method: 'POST', body: JSON.stringify(body)});
  function read() {
    let raw;
    try { raw = localStorage.getItem(KEY); } catch { throw new Error('浏览器未允许本地存储，请允许此站点保存演示记录后重试。'); }
    if (!raw) return {schema: 1, catalog: null, snapshots: []};
    let data;
    try { data = JSON.parse(raw); } catch { throw new Error('此浏览器的演示资料无法读取，请先保留已导出的资料，再检查浏览器存储。'); }
    if (data.schema !== 1 || !Array.isArray(data.snapshots) || data.catalog && !isObject(data.catalog)) throw new Error('此浏览器的工作空间格式不受支持，现有记录未被覆盖。');
    return data;
  }
  function write(data) {
    try { localStorage.setItem(KEY, JSON.stringify(data)); }
    catch { throw new Error('浏览器存储空间不足或未获允许，本次保存未完成。请先导出需要的资料和快照。'); }
  }
  function mutate(operation) {
    if (navigator.locks?.request) return navigator.locks.request(LOCK, operation);
    const pending = serial.then(operation, operation);
    serial = pending.catch(() => {});
    return pending;
  }
  function dateCode() {
    const parts = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Singapore', year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(new Date());
    return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type).value).join('');
  }
  function randomId() { return crypto.randomUUID().replace(/-/g, ''); }
  async function hash(value) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(value)));
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  }
  async function catalog() {
    const stored = read();
    if (stored.catalog) return copy(stored.catalog);
    return mutate(async () => {
      const current = read();
      if (current.catalog) return copy(current.catalog);
      const seed = await remote('/api/catalog');
      if (!isObject(seed) || !Array.isArray(seed.rate_plans)) throw new Error('预置资料格式有误，请稍后重试。');
      current.catalog = seed;
      write(current);
      return copy(seed);
    });
  }
  async function calculate(request, selectedCatalog) {
    const selected = selectedCatalog || await catalog();
    const result = await remotePost('/api/calculate', {request, catalog: selected});
    if (!isObject(result) || !Array.isArray(result.results)) throw new Error('运费测算结果格式有误，请稍后重试。');
    result.catalog_version = selected.version;
    result.catalog_hash = result.catalog_hash || await hash(selected);
    return result;
  }
  function summary(item) {
    const request = item.request, results = item.result.results || [];
    const first = results[0] || {};
    return {
      id: item.id, group_id: item.group_id, number: item.number, revision: item.revision, created_at: item.created_at,
      product_name: first.product_name || request.product_id || '', quantities: request.quantities || [],
      destination_id: request.destination_id, route_label: first.route_label || '', metadata: request.metadata || {},
      results: results.map(row => Object.fromEntries(['quantity', 'mode', 'supplier_name', 'budget_total', 'known_budget', 'per_set', 'status'].map(key => [key, row[key] ?? null])))
    };
  }
  async function request(path, options = {}) {
    const url = new URL(path, location.origin);
    const method = (options.method || 'GET').toUpperCase();
    let body = {};
    if (options.body) {
      try { body = JSON.parse(options.body); } catch { throw new Error('提交资料必须是有效JSON。'); }
    }
    if (method === 'GET' && url.pathname === '/api/catalog') return catalog();
    if (method === 'POST' && url.pathname === '/api/calculate') return calculate(body);
    if (method === 'POST' && url.pathname === '/api/catalog') {
      if (!isObject(body.catalog)) throw new Error('资料必须为完整的JSON对象。');
      const candidate = copy(body.catalog);
      await remotePost('/api/catalog/validate', {catalog: candidate});
      return mutate(async () => {
        const data = read();
        candidate.version = 'CAT-' + dateCode() + '-' + randomId().slice(0, 7).toUpperCase();
        candidate.updated_at = new Date().toISOString();
        data.catalog = candidate;
        write(data);
        return {catalog: copy(candidate), version: candidate.version};
      });
    }
    if (method === 'GET' && url.pathname === '/api/sources') {
      const sources = await remote(path, options);
      return {...sources, scope: 'public_seed'};
    }
    if (method === 'POST' && ['/api/inquiry/parse', '/api/inquiry/import'].includes(url.pathname)) return remotePost(url.pathname, {...body, catalog: await catalog()});
    if (method === 'GET' && url.pathname === '/api/snapshots') {
      const query = (url.searchParams.get('q') || '').trim().toLocaleLowerCase();
      const items = read().snapshots.slice().sort((a, b) => b.created_at.localeCompare(a.created_at) || b.revision - a.revision).map(summary);
      return {items: items.filter(item => !query || JSON.stringify(item).toLocaleLowerCase().includes(query)).slice(0, 200)};
    }
    if (method === 'GET' && /^\/api\/snapshots\/[^/]+$/.test(url.pathname)) {
      const id = decodeURIComponent(url.pathname.split('/').pop());
      const item = read().snapshots.find(snapshot => snapshot.id === id);
      if (!item) throw new Error('此浏览器中找不到这条测算记录。');
      return copy(item);
    }
    if (method === 'POST' && url.pathname === '/api/snapshots') {
      if (!isObject(body.request)) throw new Error('缺少测算输入。');
      // Ensure the initial catalog exists before taking the mutation lock.
      await catalog();
      return mutate(async () => {
        const data = read(), selected = copy(data.catalog);
        if (body.expected_catalog_version && body.expected_catalog_version !== selected.version) throw new Error('资料版本已更新，请重新测算后保存，避免使用旧费率。');
        let group, revision;
        if (body.parent_id) {
          const parent = data.snapshots.find(item => item.id === body.parent_id);
          if (!parent) throw new Error('找不到原测算版本，请重新从记录打开。');
          group = parent.group_id;
          revision = Math.max(...data.snapshots.filter(item => item.group_id === group).map(item => item.revision)) + 1;
        } else {
          group = 'FE-' + dateCode() + '-' + randomId().slice(0, 6).toUpperCase();
          revision = 1;
        }
        const result = await calculate(body.request, selected);
        // Other tabs without Web Locks must never silently replace a newer rate.
        const latest = read();
        if (latest.catalog.version !== selected.version) throw new Error('资料版本已更新，请重新测算后保存。');
        const item = {id: randomId(), group_id: group, number: group + '-V' + revision, revision,
          created_at: new Date().toISOString(), request: copy(body.request), result,
          catalog_snapshot: selected, catalog_hash: result.catalog_hash, rule_version: result.engine_version};
        if (latest.snapshots.some(saved => saved.group_id === group && saved.revision === revision)) throw new Error('另一标签页已保存该版本，请重新从记录打开后再保存。');
        latest.snapshots.push(item);
        write(latest);
        return copy(item);
      });
    }
    return remote(path, options);
  }
  async function exportFile(snapshot, format) {
    if (!['pdf', 'xlsx', 'json', 'inquiry'].includes(format)) throw new Error('不支持该导出格式。');
    if (format === 'pdf' || format === 'xlsx') {
      if (!window.FreightBrowserExports?.exportFile) throw new Error('文件导出组件尚未加载，请刷新页面后重试。');
      return window.FreightBrowserExports.exportFile(snapshot, format);
    }
    return fetch('/api/export?format=' + encodeURIComponent(format), {method: 'POST', cache: 'no-store',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({snapshot})});
  }
  window.FreightWorkspace = Object.freeze({enabled, request, exportFile});
})();
