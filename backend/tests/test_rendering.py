import io
import json
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app import projects, rendering, worker
from app.main import app


class RenderWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.assets = self.root / 'assets'
        self.assets.mkdir()
        self.root_patch = patch.object(projects, 'ROOT', self.root)
        self.asset_patch = patch.object(rendering, 'ASSETS', self.assets)
        self.root_patch.start()
        self.asset_patch.start()
        self.client = TestClient(app)
        payload = {'title': 'Dog and cat', 'characters': [
            {'id': 'a' * 32, 'name': 'Dog', 'voice': projects.VOICES[0]},
            {'id': 'b' * 32, 'name': 'Cat', 'voice': projects.VOICES[1]}],
            'scenes': [{'title': 'Jungle trail', 'background': 'A lush jungle with trees', 'dialogue': [
                {'character_id': 'a' * 32, 'text': 'Hello, Cat!'},
                {'character_id': 'b' * 32, 'text': 'Hello, Dog!'}]}]}
        response = self.client.post('/api/projects', json=payload)
        self.project = response.json()
        self.project_id = self.project['id']
        for character in payload['characters']:
            for suffix in ('.onnx', '.onnx.json'):
                file = self.assets / 'voices' / (character['voice'] + suffix)
                file.parent.mkdir(exist_ok=True)
                file.write_bytes(b'mock model for testing preflight')
            image = io.BytesIO()
            Image.new('RGBA', (80, 80), '#f2ab52').save(image, format='PNG')
            self.assertEqual(self.client.post(f"/api/projects/{self.project_id}/characters/{character['id']}/image", content=image.getvalue()).status_code, 200)

    def tearDown(self):
        self.client.close()
        self.root_patch.stop()
        self.asset_patch.stop()
        self.temp.cleanup()

    def enqueue(self):
        response = self.client.post(f'/api/projects/{self.project_id}/renders')
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()['id']

    def test_missing_models_and_images_reported(self):
        model = self.assets / 'voices' / (projects.VOICES[0] + '.onnx')
        model.unlink()
        response = self.client.post(f'/api/projects/{self.project_id}/renders')
        self.assertEqual(response.status_code, 422)
        self.assertIn('Voice files missing', response.text)
        model.write_bytes(b'model')
        projects.image_path(self.project_id, 'a' * 32).unlink()
        response = self.client.post(f'/api/projects/{self.project_id}/renders')
        self.assertEqual(response.status_code, 422)
        self.assertIn('Upload an image', response.text)

    def test_duplicate_queue_cancel_and_download_guard(self):
        job_id = self.enqueue()
        self.assertEqual(self.client.post(f'/api/projects/{self.project_id}/renders').status_code, 409)
        self.assertEqual(self.client.get(f'/api/renders/{job_id}/video').status_code, 404)
        self.assertEqual(self.client.post(f'/api/renders/{job_id}/cancel').json()['status'], 'cancelled')
        self.assertIsNone(worker.claim())
        jobs = self.client.get(f'/api/projects/{self.project_id}/renders/latest').json()
        self.assertEqual(jobs['id'], job_id)
        self.assertNotIn('snapshot', jobs)

    def test_snapshot_survives_project_edits(self):
        job_id = self.enqueue()
        self.project['scenes'][0]['dialogue'][0]['text'] = 'Changed after enqueue'
        self.client.put(f'/api/projects/{self.project_id}', json=self.project)
        snapshot = json.loads(rendering.get_job(job_id)['snapshot'])
        self.assertEqual(snapshot['scenes'][0]['dialogue'][0]['text'], 'Hello, Cat!')
        self.assertTrue((rendering.job_folder(job_id) / ('a' * 32 + '.png')).is_file())

    def test_long_dialogue_rejected_for_render(self):
        self.project['scenes'][0]['dialogue'][0]['text'] = 'x' * 351
        self.client.put(f'/api/projects/{self.project_id}', json=self.project)
        self.assertEqual(self.client.post(f'/api/projects/{self.project_id}/renders').status_code, 422)

    def test_cancel_stops_worker_commands(self):
        job_id = self.enqueue()
        self.client.post(f'/api/renders/{job_id}/cancel')
        with self.assertRaises(worker.Cancelled):
            worker.run(['not-a-real-command'], rendering.job_folder(job_id), job_id)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg is required')
    def test_actual_mp4_mux_and_preview_with_stub_speech(self):
        # Real frames and FFmpeg; speech is stubbed to avoid downloading models in tests.
        job_id = self.enqueue()
        claimed = worker.claim()
        self.assertEqual(claimed['id'], job_id)
        actual_run = worker.run
        spoken_voices = []
        def run(command, folder, current_id, timeout=600):
            if '-m' in command and 'piper' in command:
                spoken_voices.append(command[command.index('-m', 3) + 1])
                output = command[command.index('-f') + 1]
                with wave.open(output, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(22050)
                    wav.writeframes(b'\0\0' * 11025)
            else:
                actual_run(command, folder, current_id, timeout)
        with patch.object(worker, 'run', side_effect=run):
            worker.render(claimed)
        self.assertEqual(len(set(spoken_voices)), 2)
        self.assertEqual(rendering.get_job(job_id)['status'], 'completed')
        path = rendering.job_folder(job_id) / 'video.mp4'
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], capture_output=True, text=True, check=True)
        info = json.loads(probe.stdout)
        self.assertEqual({s['codec_type'] for s in info['streams']}, {'video', 'audio'})
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        self.assertEqual((video['width'], video['height']), (1280, 720))
        self.assertGreater(float(info['format']['duration']), 1.5)
        self.assertEqual(self.client.get(f'/api/renders/{job_id}/video').status_code, 200)
        partial = self.client.get(f'/api/renders/{job_id}/video', headers={'Range': 'bytes=0-99'})
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(len(partial.content), 100)
        self.assertIn('attachment', self.client.get(f'/api/renders/{job_id}/video?download=true').headers['content-disposition'])
        self.assertIn('jungle', self.client.get(f'/api/renders/{job_id}/credits').text)


if __name__ == '__main__':
    unittest.main()
