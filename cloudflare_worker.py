"""Cloudflare Python Worker: same Decimal engine, no shared visitor database."""
from urllib.parse import urlsplit, parse_qs, quote
from workers import WorkerEntrypoint, Response
from js import Request

from calculator import InputError, ENGINE_VERSION
from public_service import (MAX_BODY, dumps, parse_body, checked_catalog,
                            calculate_public, validate_public, checked_snapshot,
                            parse_inquiry, import_public)


HEADERS = {
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Robots-Tag': 'noindex',
}
FORMATS = {
    'pdf': ('application/pdf', '.pdf'),
    'xlsx': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx'),
    'json': ('application/json; charset=utf-8', '.json'),
    'inquiry': ('text/plain; charset=utf-8', '_待询价.txt'),
}


def json_response(value, status=200):
    return Response(dumps(value), status=status,
                    headers={**HEADERS, 'Content-Type': 'application/json; charset=utf-8'})


class Default(WorkerEntrypoint):
    async def asset_json(self, origin, path):
        response = await self.env.ASSETS.fetch(Request.new(origin + path))
        if response.status != 200:
            raise RuntimeError('Missing deployment asset')
        return parse_body(str(await response.text()))

    async def seed(self, origin):
        if not hasattr(self, '_seed_catalog'):
            self._seed_catalog = checked_catalog(await self.asset_json(origin, '/sources/catalog.json'))
        return self._seed_catalog

    async def pdf_font(self, origin):
        if not hasattr(self, '_font_bytes'):
            response = await self.env.ASSETS.fetch(Request.new(origin + '/fonts/NotoSansSC-Regular.ttf'))
            if response.status != 200:
                raise RuntimeError('PDF font asset is missing')
            self._font_bytes = await response.bytes()
        return self._font_bytes

    async def fetch(self, request):
        parsed = urlsplit(str(request.url))
        path = parsed.path
        origin = parsed.scheme + '://' + parsed.netloc
        method = str(request.method)
        if not path.startswith('/api/'):
            return await self.env.ASSETS.fetch(request)
        try:
            if method == 'GET':
                if path == '/api/health':
                    return json_response({'ok': True, 'app': 'procurement',
                                          'version': ENGINE_VERSION, 'deployment': 'cloudflare',
                                          'workspace_storage': 'visitor_browser',
                                          'server_persistence': False})
                if path == '/api/catalog':
                    return json_response(await self.seed(origin))
                if path == '/api/sources':
                    manifest = await self.asset_json(origin, '/sources/source_manifest.json')
                    return json_response({'items': manifest.get('items', []),
                                          'catalog_version': manifest.get('catalog_version'),
                                          'scope': 'preset_sources'})
                return json_response({'error': '未找到接口。'}, 404)
            if method != 'POST':
                return json_response({'error': '该接口不支持此请求方式。'}, 405)
            incoming_origin = request.headers.get('Origin')
            fetch_site = request.headers.get('Sec-Fetch-Site')
            if incoming_origin and str(incoming_origin) != origin or fetch_site and str(fetch_site) == 'cross-site':
                return json_response({'error': '请从本工作台页面提交测算。'}, 403)
            content_type = str(request.headers.get('Content-Type') or '').split(';')[0].strip()
            if content_type != 'application/json':
                return json_response({'error': '请求格式必须为application/json。'}, 415)
            size = request.headers.get('Content-Length')
            if size and int(str(size)) > MAX_BODY:
                return json_response({'error': '请求大于4MB，请拆分资料。'}, 413)
            body = parse_body(str(await request.text()))
            if path == '/api/calculate':
                return json_response(calculate_public(body, await self.seed(origin)))
            if path == '/api/catalog/validate':
                return json_response(validate_public(body))
            if path == '/api/inquiry/parse':
                catalog = checked_catalog(body.get('catalog', await self.seed(origin)))
                return json_response(parse_inquiry(body.get('text'), catalog))
            if path == '/api/inquiry/import':
                return json_response(import_public(body, await self.seed(origin)))
            if path == '/api/export':
                fmt = parse_qs(parsed.query).get('format', [''])[0]
                if fmt not in FORMATS:
                    return json_response({'error': '不支持的导出格式。'}, 400)
                snapshot = checked_snapshot(body.get('snapshot'))
                # Imports remain lazy so ordinary calculations do not load export packages.
                from portable_documents import export_pdf, export_xlsx, export_json, export_inquiry
                if fmt == 'pdf':
                    data = export_pdf(snapshot, await self.pdf_font(origin))
                else:
                    data = {'xlsx': export_xlsx, 'json': export_json, 'inquiry': export_inquiry}[fmt](snapshot)
                mime, extension = FORMATS[fmt]
                filename = '内部运费测算_' + snapshot['number'] + extension
                return Response(data, headers={**HEADERS, 'Content-Type': mime,
                    'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename)})
            return json_response({'error': '未找到接口。'}, 404)
        except (InputError, ValueError, TypeError, KeyError) as exc:
            # Validation failures expose only the business-readable error, not visitor data.
            message = str(exc) if isinstance(exc, (InputError, ValueError)) else '请求资料不完整或格式不正确。'
            return json_response({'error': message or '请求资料不正确。'}, 400)
        except Exception:
            # Never log uploaded catalog/snapshot contents or exception paths on the public API.
            return json_response({'error': '处理暂未完成，请稍后再试。测算记录仍保存在此浏览器。'}, 500)
