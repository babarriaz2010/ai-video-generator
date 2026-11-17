"""Single CPU worker: Piper speech -> illustrated frames -> H.264/AAC MP4."""
import json
import math
import random
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import rendering as jobs


class Cancelled(Exception):
    pass


def check_cancel(job_id):
    if jobs.get_job(job_id)['status'] == 'cancelled':
        raise Cancelled()


def run(command, folder, job_id, timeout=600):
    check_cancel(job_id)
    with (folder / 'command.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=folder, stdout=log, stderr=log)
        started = time.monotonic()
        try:
            while process.poll() is None:
                check_cancel(job_id)
                if time.monotonic() - started > timeout:
                    raise RuntimeError('Generation command timed out. Try shorter dialogue lines.')
                time.sleep(0.3)
            if process.returncode:
                detail = (folder / 'command.log').read_text(encoding='utf-8', errors='replace')[-1600:]
                raise RuntimeError('Generation command failed: ' + detail)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def font(size):
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'C:/Windows/Fonts/arial.ttf'):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def wrapped(draw, text, face, width):
    words = text.split()
    lines, current = [], ''
    for word in words:
        # Split unusually long words rather than allowing text outside the frame.
        pieces = []
        while draw.textlength(word, font=face) > width:
            cut = max(1, len(word) // 2)
            while cut > 1 and draw.textlength(word[:cut], font=face) > width:
                cut -= 1
            pieces.append(word[:cut])
            word = word[cut:]
        pieces.append(word)
        for piece in pieces:
            candidate = (current + ' ' + piece).strip()
            if current and draw.textlength(candidate, font=face) > width:
                lines.append(current)
                current = piece
            else:
                current = candidate
    if current:
        lines.append(current)
    return lines


def background(description, credits):
    """Use a tagged local photo if matched, otherwise draw an original themed setting."""
    text = description.casefold()
    candidates = []
    for metadata in sorted((jobs.ASSETS / 'backgrounds').glob('*.credits.json')):
        try:
            entry = json.loads(metadata.read_text(encoding='utf-8'))
            image_path = metadata.with_name(entry['filename'])
            if image_path.parent != metadata.parent or entry.get('generated'):
                continue
            score = sum(1 for tag in entry.get('tags', []) if tag.casefold() in text)
            if score and image_path.is_file():
                candidates.append((score, image_path, entry))
        except (ValueError, KeyError, OSError):
            continue
    if candidates:
        _, path, credit = max(candidates, key=lambda item: item[0])
        with Image.open(path) as image:
            result = ImageOps.fit(image.convert('RGB'), (1280, 720))
        credits.append(credit)
        return result
    jungle = any(word in text for word in ('jungle', 'forest', 'trees', 'park'))
    image = Image.new('RGB', (1280, 720), '#285c42' if jungle else '#253b60')
    draw = ImageDraw.Draw(image)
    if jungle:
        rng = random.Random(42)
        draw.ellipse((700, -80, 1150, 400), fill='#729c68')
        draw.polygon([(700, 370), (790, 370), (1120, 720), (440, 720)], fill='#4b9292')
        for x in (-25, 110, 1130, 1250):
            draw.rectangle((x, 0, x + 65, 580), fill='#254334')
            for _ in range(18):
                cx, cy = x + rng.randint(-130, 170), rng.randint(-120, 230)
                draw.ellipse((cx - 100, cy - 55, cx + 100, cy + 65), fill=rng.choice(['#183f2c', '#356c3c', '#447f47']))
        for x in range(50, 1280, 160):
            draw.arc((x, -100, x + 140, 290), 0, 150, fill='#80a05a', width=4)
    credits.append({'source': 'Original procedural jungle illustration' if jungle else 'Original neutral background',
                    'license': 'CC0-1.0', 'generated': True})
    return image


def frame(background_image, scene, characters, speaker, text, folder, target):
    image = background_image.copy().convert('RGBA')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1280, 75), fill=(12, 24, 26, 230))
    draw.text((36, 22), scene['title'][:75], font=font(27), fill='white')
    ids = list(dict.fromkeys(line['character_id'] for line in scene['dialogue']))
    card_width = min(350, (1200 - 20 * (len(ids) - 1)) // len(ids))
    start = (1280 - (card_width + 20) * len(ids) + 20) // 2
    for index, character_id in enumerate(ids):
        x = start + index * (card_width + 20)
        active = character_id == speaker['id']
        draw.rounded_rectangle((x, 110, x + card_width, 493), radius=16,
                               fill=(18, 33, 32, 215), outline='#a6e8ac' if active else '#648479', width=5 if active else 2)
        with Image.open(folder / (character_id + '.png')) as source:
            source = source.convert('RGBA')
            source.thumbnail((card_width - 28, 305))
            image.alpha_composite(source, (x + (card_width - source.width) // 2, 125 + (305 - source.height) // 2))
        name = characters[character_id]['name']
        face = font(22)
        while draw.textlength(name, font=face) > card_width - 16 and face.size > 10:
            face = font(face.size - 1)
        draw.text((x + card_width // 2, 455), name, anchor='mm', font=face, fill='#b7ffbc' if active else 'white')
    draw.rounded_rectangle((30, 515, 1250, 705), radius=18, fill=(10, 18, 26, 245))
    draw.text((55, 530), speaker['name'] + ':', font=font(22), fill='#b7ffbc')
    face = font(25)
    lines = wrapped(draw, text, face, 1160)
    while len(lines) > 4 and face.size > 12:
        face = font(face.size - 1)
        lines = wrapped(draw, text, face, 1160)
    for index, line in enumerate(lines):
        draw.text((55, 563 + index * (face.size + 5)), line, font=face, fill='white')
    image.convert('RGB').save(target)


def render(job):
    job_id = job['id']
    folder = jobs.job_folder(job_id).resolve()
    snapshot = json.loads(job['snapshot'])
    characters = {c['id']: c for c in snapshot['characters']}
    total = sum(len(scene['dialogue']) for scene in snapshot['scenes'])
    credits, parts = [], []
    count = 0
    for scene in snapshot['scenes']:
        check_cancel(job_id)
        bg = background(scene['background'], credits)
        for line in scene['dialogue']:
            check_cancel(job_id)
            if shutil.disk_usage(folder).free < 200 * 1024 * 1024:
                raise RuntimeError('Storage is nearly full. Free space on the storage drive and generate again.')
            speaker = characters[line['character_id']]
            jobs.update_job(job_id, 'running', int(count / total * 90), f"Generating speech {count + 1}/{total}: {speaker['name']}")
            prefix = f'line-{count:04d}'
            text_file = folder / (prefix + '.txt')
            text_file.write_text(line['text'], encoding='utf-8')
            audio = folder / (prefix + '.wav')
            model = (jobs.ASSETS / 'voices' / (speaker['voice'] + '.onnx')).resolve()
            run([sys.executable, '-m', 'piper', '-m', str(model), '-f', str(audio), '--input-file', str(text_file)], folder, job_id, timeout=300)
            with wave.open(str(audio)) as wav:
                duration = wav.getnframes() / wav.getframerate() + 0.3
            if not math.isfinite(duration) or duration <= 0.3:
                raise RuntimeError('Speech generator returned empty audio')
            poster = folder / (prefix + '.png')
            frame(bg, scene, characters, speaker, line['text'], folder, poster)
            clip = folder / (prefix + '.mp4')
            jobs.update_job(job_id, 'running', int(count / total * 90), f'Rendering dialogue {count + 1}/{total}')
            run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-loop', '1', '-framerate', '24', '-i', str(poster),
                 '-i', str(audio), '-t', str(round(duration, 3)), '-af', 'apad=pad_dur=0.3', '-c:v', 'libx264',
                 '-preset', 'ultrafast', '-crf', '23', '-pix_fmt', 'yuv420p', '-threads', '2',
                 '-c:a', 'aac', '-ar', '44100', '-ac', '2', '-b:a', '128k', str(clip)], folder, job_id)
            parts.append(f"file '{clip.name}'")
            count += 1
    jobs.update_job(job_id, 'running', 95, 'Assembling final video')
    (folder / 'clips.txt').write_text('\n'.join(parts), encoding='utf-8')
    run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '1', '-i', 'clips.txt',
         '-c', 'copy', '-movflags', '+faststart', 'video.partial.mp4'], folder, job_id)
    (folder / 'credits.json').write_text(json.dumps(credits, indent=2), encoding='utf-8')
    check_cancel(job_id)
    (folder / 'video.partial.mp4').replace(folder / 'video.mp4')
    jobs.update_job(job_id, 'completed', 100, 'Video ready. Render uses the project version saved when generation started.')
    # These are worker-created intermediates in this job folder only.
    for path in folder.glob('line-*'):
        try:
            path.unlink()
        except OSError:
            pass


def claim():
    with jobs.database() as db:
        jobs.schema(db)
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT id FROM renders WHERE status='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
        if row:
            db.execute("UPDATE renders SET status='running',message='Starting render' WHERE id=?", (row[0],))
    return jobs.get_job(row[0]) if row else None


def main():
    # This service intentionally has exactly one worker. Resume interrupted jobs on restart.
    with jobs.database() as db:
        jobs.schema(db)
        db.execute("UPDATE renders SET status='queued',message='Resuming after worker restart' WHERE status='running'")
    print('Render worker ready', flush=True)
    while True:
        job = claim()
        if job:
            try:
                render(job)
            except Cancelled:
                print(f"Cancelled {job['id']}", flush=True)
            except Exception as error:
                jobs.update_job(job['id'], 'failed', 0, str(error)[-1800:])
                print(f"Render failed {job['id']}: {error}", flush=True)
        else:
            time.sleep(1)


if __name__ == '__main__':
    main()
