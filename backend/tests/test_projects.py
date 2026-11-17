import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app import projects


class ProjectWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch.object(projects, 'ROOT', self.root)
        self.patch.start()
        self.client = TestClient(app)
        self.payload = {
            'title': 'A walk',
            'characters': [
                {'id': 'a' * 32, 'name': 'Ali', 'voice': projects.VOICES[0]},
                {'id': 'b' * 32, 'name': 'Sara', 'voice': projects.VOICES[1]},
            ],
            'transcript': '# The park\nBackground: A sunny park\nAli: Hello!\nSara: Hi!\nAli: Walk?\nSara: Yes.',
            'scenes': [],
        }

    def tearDown(self):
        self.client.close()
        self.patch.stop()
        self.temp.cleanup()

    def create(self):
        response = self.client.post('/api/projects', json=self.payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def test_save_parse_edit_and_reopen_from_disk(self):
        project_id = self.create()
        draft = self.client.post('/api/parse', json=self.payload)
        self.assertEqual(draft.status_code, 200, draft.text)
        self.payload['scenes'] = draft.json()['scenes']
        self.assertEqual(len(self.payload['scenes'][0]['dialogue']), 4)
        self.payload['scenes'][0]['dialogue'][0]['text'] = 'Updated dialogue'
        self.assertEqual(self.client.put(f'/api/projects/{project_id}', json=self.payload).status_code, 200)
        # Read SQLite directly through a fresh connection to verify durable storage.
        with closing(sqlite3.connect(self.root / 'projects.sqlite3')) as db:
            stored = json.loads(db.execute('SELECT data FROM projects WHERE id=?', (project_id,)).fetchone()[0])
        with TestClient(app) as new_client:
            reopened = new_client.get(f'/api/projects/{project_id}').json()
        self.assertEqual(reopened, stored)
        self.assertEqual(reopened['scenes'][0]['dialogue'][0]['text'], 'Updated dialogue')
        self.assertEqual(self.client.get('/api/projects').json()[0]['id'], project_id)

    def test_unknown_speaker_does_not_destroy_saved_scenes(self):
        project_id = self.create()
        self.payload['transcript'] = 'Unknown: Hello'
        response = self.client.post('/api/parse', json=self.payload)
        self.assertEqual(response.status_code, 422)
        self.assertIn('Line 1', response.text)
        self.assertEqual(self.client.get(f'/api/projects/{project_id}').json()['transcript'].splitlines()[0], '# The park')

    def test_duplicate_names_and_dangling_dialogue_rejected(self):
        self.payload['characters'][1]['name'] = ' ali '
        self.assertEqual(self.client.post('/api/projects', json=self.payload).status_code, 422)
        self.payload['characters'][1]['name'] = 'Sara'
        self.payload['scenes'] = [{'title': 'Test', 'dialogue': [{'character_id': 'unknown', 'text': 'Hello'}]}]
        self.assertEqual(self.client.post('/api/projects', json=self.payload).status_code, 422)

    def test_image_upload_validation_and_reopen(self):
        project_id = self.create()
        path = f'/api/projects/{project_id}/characters/{"a" * 32}/image'
        self.assertEqual(self.client.post(path, content=b'not an image').status_code, 415)
        data = io.BytesIO()
        Image.new('RGB', (32, 32), 'red').save(data, format='JPEG')
        self.assertEqual(self.client.post(path, content=data.getvalue()).status_code, 200)
        with TestClient(app) as new_client:
            response = new_client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (32, 32))

    def test_oversize_image_body_rejected(self):
        project_id = self.create()
        response = self.client.post(f'/api/projects/{project_id}/characters/{"a" * 32}/image', content=b'x' * (10 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)

    def test_parser_limits_return_validation_error(self):
        self.payload['transcript'] = 'Ali: ' + 'x' * 5001
        self.assertEqual(self.client.post('/api/parse', json=self.payload).status_code, 422)

    def test_missing_project_and_cross_origin_preflight(self):
        self.assertEqual(self.client.get('/api/projects/missing').status_code, 404)
        self.assertEqual(self.client.put('/api/projects/missing', json=self.payload).status_code, 404)
        response = self.client.options('/api/projects', headers={
            'Origin': 'http://localhost:3000', 'Access-Control-Request-Method': 'PUT',
            'Access-Control-Request-Headers': 'content-type'})
        self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
