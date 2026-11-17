"""Explicit one-shot downloads; no model inference or app startup side effects."""
import argparse
import json
import struct
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path('/assets')
VOICE_BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/main'


def download(url, target, image=False):
    if urlparse(url).scheme != 'https':
        raise ValueError('Download URLs must use HTTPS')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size:
        print(f'Already exists: {target}', flush=True)
        return
    partial = target.with_name(target.name + '.part')
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={
                'User-Agent': 'LocalVideoGenerator/0.1 (manual asset setup)'
            })
            with urllib.request.urlopen(request, timeout=60) as response:
                if image and response.headers.get_content_type() not in ('image/jpeg', 'image/png', 'image/webp'):
                    raise ValueError('Expected a JPEG, PNG, or WebP image; use a direct image URL')
                size = 0
                expected = response.headers.get('Content-Length')
                with partial.open('wb') as output:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > 200 * 1024 * 1024:
                            raise ValueError('Asset exceeds the 200 MB download limit')
                        output.write(chunk)
                if not size or (expected and size != int(expected)):
                    raise ValueError('Empty or incomplete download')
            partial.replace(target)
            print(f'Downloaded: {target} ({size / 1024 / 1024:.1f} MB)', flush=True)
            return
        except Exception as error:
            partial.unlink(missing_ok=True)
            # Retrying a forbidden URL immediately cannot fix the rejection.
            if isinstance(error, urllib.error.HTTPError) and error.code in (403, 404, 429):
                raise
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def voices():
    for speaker in ('lessac', 'ryan'):
        name = f'en_US-{speaker}-medium'
        base = f'{VOICE_BASE}/en/en_US/{speaker}/medium'
        for filename in (name + '.onnx', name + '.onnx.json', 'MODEL_CARD'):
            destination = filename if filename != 'MODEL_CARD' else name + '-MODEL_CARD.txt'
            download(f'{base}/{filename}', ROOT / 'voices' / destination)


def local_background():
    """Create an original neutral PNG without dependencies or network access."""
    folder = ROOT / 'backgrounds'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'neutral-gradient.png'
    width, height = 1280, 720
    def chunk(kind, data):
        return (struct.pack('!I', len(data)) + kind + data
                + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff))
    if not target.exists():
        rows = bytearray()
        for y in range(height):
            ratio = y / (height - 1)
            pixel = bytes(int(a + (b - a) * ratio) for a, b in
                          zip((28, 45, 78), (110, 149, 174)))
            rows.extend(b'\x00' + pixel * width)
        png = (b'\x89PNG\r\n\x1a\n'
               + chunk(b'IHDR', struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0))
               + chunk(b'IDAT', zlib.compress(bytes(rows))) + chunk(b'IEND', b''))
        partial = target.with_suffix('.png.part')
        partial.write_bytes(png)
        partial.replace(target)
    metadata = {
        'filename': target.name, 'source': 'Generated locally by download_assets.py',
        'author': 'Local AI Video Generator', 'license': 'CC0-1.0',
        'license_url': 'https://creativecommons.org/publicdomain/zero/1.0/',
        'tags': ['neutral', 'gradient', 'fallback'], 'generated': True,
    }
    (folder / (target.name + '.credits.json')).write_text(
        json.dumps(metadata, indent=2), encoding='utf-8')
    print(f'Local background ready: {target}', flush=True)


def backgrounds():
    local_background()
    entries = json.loads(Path(__file__).with_name('backgrounds.json').read_text(encoding='utf-8'))
    failed = []
    for entry in entries:
        filename = entry['filename']
        if Path(filename).name != filename or '/' in filename or '\\' in filename:
            raise ValueError('Background filenames must not contain directories')
        if Path(filename).suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
            raise ValueError('Unsupported background extension')
        for field in ('source', 'author', 'license', 'license_url', 'tags'):
            if not entry.get(field):
                raise ValueError(f'Missing background metadata: {field}')
        try:
            download(entry['url'], ROOT / 'backgrounds' / filename, image=True)
        except (urllib.error.URLError, TimeoutError) as error:
            print(f'WARNING: Could not download {filename}: {error}. '
                  'The local neutral background is available instead.', flush=True)
            failed.append(filename)
            continue
        (ROOT / 'backgrounds' / (filename + '.credits.json')).write_text(
            json.dumps(entry, indent=2), encoding='utf-8')
    if failed:
        print('Background setup completed with local fallback; remote assets skipped: '
              + ', '.join(failed), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=('voices', 'backgrounds', 'all'))
    args = parser.parse_args()
    if args.kind in ('voices', 'all'):
        voices()
    if args.kind in ('backgrounds', 'all'):
        backgrounds()
