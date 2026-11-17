"""Persistent render jobs. Heavy work runs in the separate worker container."""
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import projects

router = APIRouter(prefix='/api')
ASSETS = Path(os.getenv('ASSETS_PATH', '/app/assets'))


def database():
    return projects.connection()


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS renders (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, status TEXT NOT NULL,
        progress INTEGER NOT NULL, message TEXT NOT NULL, snapshot TEXT NOT NULL,
        created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))''')


def job_folder(job_id):
    # IDs come from DB lookups, but validate before constructing filesystem paths.
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise HTTPException(404, 'Render not found')
    return projects.ROOT / 'renders' / job_id


def get_job(job_id):
    with database() as db:
        schema(db)
        db.row_factory = __import__('sqlite3').Row
        row = db.execute('SELECT * FROM renders WHERE id=?', (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Render not found')
    return dict(row)


def public(job):
    return {key: value for key, value in job.items() if key != 'snapshot'}


def update_job(job_id, status, progress, message):
    with database() as db:
        schema(db)
        db.execute("UPDATE renders SET status=?,progress=?,message=? WHERE id=? AND status!='cancelled'",
                   (status, progress, message, job_id))


@router.post('/projects/{project_id}/renders', status_code=202)
def create_render(project_id: str):
    snapshot = projects.read_project(project_id)
    lines = [line for scene in snapshot['scenes'] for line in scene['dialogue']]
    if not lines:
        raise HTTPException(422, 'Build a scene draft and save dialogue before rendering')
    if len(lines) > 100 or any(len(line['text']) > 350 for line in lines):
        raise HTTPException(422, 'First version supports 100 dialogue lines, up to 350 characters each. Split longer lines.')
    for scene in snapshot['scenes']:
        if not scene['dialogue']:
            raise HTTPException(422, 'Remove empty scenes or add dialogue before rendering')
        if len({line['character_id'] for line in scene['dialogue']}) > 4:
            raise HTTPException(422, 'Use at most four speaking characters in each scene')
    characters = {c['id']: c for c in snapshot['characters']}
    used = {line['character_id'] for line in lines}
    for character_id in used:
        character = characters[character_id]
        for suffix in ('.onnx', '.onnx.json'):
            if not (ASSETS / 'voices' / (character['voice'] + suffix)).is_file():
                raise HTTPException(422, f"Voice files missing for {character['name']}. Run the voice download command first.")
        if not projects.image_path(project_id, character_id).is_file():
            raise HTTPException(422, f"Upload an image for {character['name']} first")
    if shutil.disk_usage(projects.ROOT).free < 500 * 1024 * 1024:
        raise HTTPException(422, 'Free at least 500 MB in the project storage drive before rendering')
    job_id = uuid4().hex
    folder = job_folder(job_id)
    try:
        with database() as db:
            schema(db)
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM renders WHERE status IN ('queued','running')").fetchone():
                raise HTTPException(409, 'Another video is queued or rendering. Wait or cancel it first.')
            folder.mkdir(parents=True)
            for character_id in used:
                shutil.copyfile(projects.image_path(project_id, character_id), folder / (character_id + '.png'))
            db.execute('INSERT INTO renders (id,project_id,status,progress,message,snapshot) VALUES (?,?,?,?,?,?)',
                       (job_id, project_id, 'queued', 0, 'Queued. Waiting for the render worker.', json.dumps(snapshot)))
    except Exception:
        # Only remove this newly allocated job directory, never a project directory.
        if folder.exists():
            shutil.rmtree(folder)
        raise
    return public(get_job(job_id))


@router.get('/projects/{project_id}/renders/latest')
def latest_render(project_id: str):
    projects.read_project(project_id)
    with database() as db:
        schema(db)
        row = db.execute('SELECT id FROM renders WHERE project_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1', (project_id,)).fetchone()
    return public(get_job(row[0])) if row else None


@router.get('/renders/{job_id}')
def render_status(job_id: str):
    return public(get_job(job_id))


@router.post('/renders/{job_id}/cancel')
def cancel_render(job_id: str):
    get_job(job_id)
    with database() as db:
        db.execute("UPDATE renders SET status='cancelled', message='Cancelled' WHERE id=? AND status IN ('queued','running')", (job_id,))
    return public(get_job(job_id))


@router.get('/renders/{job_id}/video')
def video(job_id: str, download: bool = False):
    job = get_job(job_id)
    target = job_folder(job_id) / 'video.mp4'
    if job['status'] != 'completed' or not target.is_file():
        raise HTTPException(404, 'Video is not ready')
    return FileResponse(target, media_type='video/mp4', filename='video.mp4' if download else None)


@router.get('/renders/{job_id}/credits')
def credits(job_id: str):
    job = get_job(job_id)
    target = job_folder(job_id) / 'credits.json'
    if job['status'] != 'completed' or not target.is_file():
        raise HTTPException(404, 'Credits are not ready')
    return FileResponse(target, media_type='application/json', filename='background-credits.json')
