"""Build only reviewed public demo assets; never copy databases or customer mail."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]


def build():
    generated = ROOT / 'worker'
    generated.mkdir(exist_ok=True)
    for name in ('cloudflare_worker.py', 'calculator.py', 'demo_estimation.py', 'inquiry.py', 'public_service.py', 'portable_documents.py'):
        shutil.copy2(ROOT / name, generated / name)
    target = ROOT / 'dist'
    target.mkdir(exist_ok=True)
    for name in ('index.html', 'app.js', 'style.css', 'public-workspace.js'):
        shutil.copy2(ROOT / 'static' / name, target / name)
    for folder, source in [('sources', ROOT / 'materials/sources'), ('fonts', ROOT / 'assets/fonts')]:
        dest = target / folder
        dest.mkdir(exist_ok=True)
        for path in source.iterdir():
            if path.is_file() and path.suffix in {'.json', '.csv', '.xlsx', '.md', '.ttf', '.txt'}:
                shutil.copy2(path, dest / path.name)
    headers = '''/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  X-Frame-Options: DENY
  Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'
/sources/*
  Content-Disposition: attachment
/fonts/*
  Cache-Control: public, max-age=86400
'''
    (target / '_headers').write_text(headers)
    manifest = []
    for p in sorted(target.rglob('*')):
        if p.is_file():
            manifest.append({'path': str(p.relative_to(target)), 'bytes': p.stat().st_size,
                             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    print(json.dumps({'public_assets': len(manifest), 'bytes': sum(x['bytes'] for x in manifest)}, ensure_ascii=False))
    return manifest


if __name__ == '__main__':
    build()
