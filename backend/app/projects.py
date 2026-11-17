import io
import json
import os
import re
import sqlite3
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError, model_validator

router = APIRouter(prefix='/api')
ROOT = Path(os.getenv('STORAGE_PATH', '/app/storage'))
VOICES = ('en_US-lessac-medium', 'en_US-ryan-medium')


@contextmanager
def connection():
    ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / 'projects.sqlite3', timeout=15)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            yield db
    finally:
        db.close()


class Character(BaseModel):
    id: str = Field(pattern=r'^[a-f0-9]{32}$')
    name: str = Field(min_length=1, max_length=80)
    voice: Literal['en_US-lessac-medium', 'en_US-ryan-medium'] = VOICES[0]


class Line(BaseModel):
    character_id: str
    text: str = Field(min_length=1, max_length=5000)


class Scene(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    background: str = Field(default='', max_length=1000)
    dialogue: list[Line] = Field(default_factory=list, max_length=500)


class Project(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    transcript: str = Field(default='', max_length=100000)
    characters: list[Character] = Field(default_factory=list, max_length=30)
    scenes: list[Scene] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def validate_references(self):
        if not self.title.strip():
            raise ValueError('Project title cannot be blank')
        names = [c.name.strip().casefold() for c in self.characters]
        ids = [c.id for c in self.characters]
        if any(not n or ':' in n for n in names) or len(set(names)) != len(names):
            raise ValueError('Character names must be unique, nonblank and contain no colon')
        if any(n == 'background' or n.startswith('# ') for n in names):
            raise ValueError('Background and scene headings are reserved; choose another character name')
        if len(set(ids)) != len(ids):
            raise ValueError('Character IDs must be unique')
        if any(line.character_id not in ids for s in self.scenes for line in s.dialogue):
            raise ValueError('Dialogue references an unknown character')
        if any(not line.text.strip() for s in self.scenes for line in s.dialogue):
            raise ValueError('Dialogue text cannot be blank')
        return self


def read_project(project_id):
    with connection() as db:
        row = db.execute('SELECT data FROM projects WHERE id=?', (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Project not found')
    return json.loads(row[0])


def write_project(project_id, project, create=False):
    record = {**project.model_dump(), 'id': project_id,
              'updated_at': datetime.now(timezone.utc).isoformat()}
    with connection() as db:
        if create:
            db.execute('INSERT INTO projects VALUES (?,?)', (project_id, json.dumps(record)))
        else:
            result = db.execute('UPDATE projects SET data=? WHERE id=?', (json.dumps(record), project_id))
            if not result.rowcount:
                raise HTTPException(404, 'Project not found')
    return record


@router.get('/projects')
def list_projects():
    with connection() as db:
        records = [json.loads(row[0]) for row in db.execute('SELECT data FROM projects')]
    return sorted([{'id': p['id'], 'title': p['title'], 'updated_at': p['updated_at']}
                   for p in records], key=lambda p: p['updated_at'], reverse=True)


@router.post('/projects', status_code=201)
def create_project(project: Project):
    return write_project(uuid4().hex, project, create=True)


@router.get('/projects/{project_id}')
def get_project(project_id: str):
    return read_project(project_id)


@router.put('/projects/{project_id}')
def update_project(project_id: str, project: Project):
    return write_project(project_id, project)


@router.post('/parse')
def parse_transcript(project: Project):
    names = {c.name.strip().casefold(): c.id for c in project.characters}
    scenes, errors = [], []
    scene = None
    for number, raw in enumerate(project.transcript.splitlines(), 1):
        text = raw.strip()
        if not text:
            continue
        if text.startswith('# '):
            scene = {'title': text[2:].strip()[:200] or 'Untitled scene', 'background': '', 'dialogue': []}
            scenes.append(scene)
            continue
        if scene is None:
            scene = {'title': 'Scene 1', 'background': '', 'dialogue': []}
            scenes.append(scene)
        if text.casefold().startswith('background:'):
            scene['background'] = text.split(':', 1)[1].strip()
            continue
        name, separator, dialogue = text.partition(':')
        character_id = names.get(name.strip().casefold())
        if not separator or not character_id or not dialogue.strip():
            errors.append(f'Line {number}: use a known Character: dialogue, # Scene title, or Background: description.')
        else:
            scene['dialogue'].append({'character_id': character_id, 'text': dialogue.strip()})
    if errors:
        raise HTTPException(422, errors)
    if not any(s['dialogue'] for s in scenes):
        raise HTTPException(422, 'Add at least one dialogue line')
    # Enforce the same limits used when saving edited scenes.
    try:
        validated = Project(**{**project.model_dump(), 'scenes': scenes})
    except ValidationError:
        raise HTTPException(422, 'Scene draft exceeds limits: 100 scenes, 500 lines per scene, '
                            '5000 characters per line, 1000 characters per background')
    return {'scenes': [s.model_dump() for s in validated.scenes]}


def image_path(project_id, character_id):
    project = read_project(project_id)
    if not any(c['id'] == character_id for c in project['characters']):
        raise HTTPException(404, 'Character not found; save the character first')
    if not re.fullmatch(r'[a-f0-9]{32}', project_id + '') or not re.fullmatch(r'[a-f0-9]{32}', character_id):
        raise HTTPException(404, 'Invalid ID')
    return ROOT / 'projects' / project_id / 'characters' / (character_id + '.png')


@router.post('/projects/{project_id}/characters/{character_id}/image')
async def upload_image(project_id: str, character_id: str, request: Request):
    target = image_path(project_id, character_id)
    data = bytearray()
    async for part in request.stream():
        data.extend(part)
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, 'Image must be 10 MB or smaller')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP'):
                    raise HTTPException(415, 'Use a PNG, JPEG or WebP image')
                if image.width * image.height > 20000000:
                    raise HTTPException(413, 'Image must be 20 megapixels or smaller')
                image.load()
                image = image.convert('RGBA')
                image.thumbnail((2048, 2048))
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(uuid4().hex + '.tmp')
                try:
                    image.save(temporary, format='PNG')
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise HTTPException(415, 'Invalid or oversized image')
    return {'status': 'saved'}


@router.get('/projects/{project_id}/characters/{character_id}/image')
def get_image(project_id: str, character_id: str):
    target = image_path(project_id, character_id)
    if not target.is_file():
        raise HTTPException(404, 'No image uploaded')
    return FileResponse(target, media_type='image/png')
