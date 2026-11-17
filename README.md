# Local AI Video Generator — Project Editor

Requires Docker Desktop with Linux containers enabled.

From the directory containing `docker-compose.yml`, run:

```powershell
docker compose up --build -d
docker compose ps
```

Open:
- React dashboard: http://localhost:3000
- FastAPI health: http://localhost:8000/api/health
- FFmpeg detection: http://localhost:8000/api/system
- FastAPI docs: http://localhost:8000/docs

Stop with `docker compose down`. Your `storage/` files are preserved.

If a container is unhealthy, use `docker compose logs --tail=100`.

The dashboard supports saved projects, transcript input, character reference images,
voice selection, editable scene drafts and local MP4 generation with speech and subtitles.

## Generate your saved project with speech

Rebuild to install Piper and start the dedicated CPU worker:

```cmd
docker compose up --build -d backend frontend worker
```

Open http://localhost:3000, select your saved project, and confirm all speaking characters
have reference images and assigned voices. Save the scene draft, scroll to **Video with speech**,
and click **Generate video with speech**. Wait for completion, then play the preview or
click **Download MP4**. Download background credits alongside any photo-based video.
The optional Ollama server is not needed for rendering.

The worker uses the downloaded Piper models under `assets/voices`. Missing files are reported
before queueing. Download them if needed:

```cmd
docker compose --profile setup run --rm --no-deps asset-download voices
```

- Output: 1280x720, 24 fps, H.264 video and AAC speech, with subtitles drawn into each shot.
- Each character uses its selected voice. Still reference images appear in cards; the speaker is highlighted.
- Tagged local background photos are matched against scene descriptions. Otherwise jungle/forest/park
  descriptions receive an original procedural jungle illustration; other settings get a neutral background.
  This does not generate photorealistic scenery or animate mouths.
- Keep dialogue lines at 350 characters or fewer; split longer lines in the editor. Up to 100 lines
  and four speaking characters per scene are supported. Remove empty scenes before rendering.
- One render runs at a time across projects. You can cancel and start again. Progress is stored in SQLite;
  on worker restart, an interrupted job restarts from its saved snapshot, regenerating its lines.
- Images and project data are copied at generation start, so later edits do not alter a running render.
  Voice/background files should remain unchanged until rendering completes.
- Final output and credits persist under `/app/storage/renders/<job-id>/`. Successful renders remove
  intermediate line clips; failed/cancelled jobs retain intermediates for diagnosis.
- Piper/ONNX is installed during the image build; synthesis does not download voices automatically.

If generation remains queued, check the worker:

```cmd
docker compose ps
docker compose logs --tail=100 worker
```

## Open the project editor

After this update, rebuild to install the backend image-validation dependency:

```cmd
docker compose up --build -d backend frontend worker
```

Open http://localhost:3000. Add characters named Ali and Sara, choose their voices,
and upload PNG/JPEG/WebP images (up to 10 MB and 20 megapixels; normalized to PNG).
Uploading an image saves the project first. Enter this sample transcript:

```text
# A morning walk
Background: A quiet park in daylight
Ali: Shall we take a walk?
Sara: Yes, the weather is lovely.
Ali: Let us go to the lake.
Sara: That sounds good.
```

Click **Build scene draft**, review/edit the scene and dialogue, then **Save project**.
Reopen the project from the sidebar after refreshing. Save is explicit, not automatic;
the editor warns before discarding unsaved changes. Parsing uses your headings and
speaker names, not the optional language model. Unrecognized lines return errors
without replacing the existing scene edits. Background descriptions guide the renderer's local background choice.

SQLite lives at `/app/storage/projects.sqlite3`; images live under `/app/storage/projects/`.
Both persist in the host folder selected by `STORAGE_PATH` in `.env`.
The project API is available in http://localhost:8000/docs.

Backend workflow checks (installs `httpx` in a temporary test container):

```cmd
docker compose run --rm --no-deps -v "./backend/tests:/app/tests:ro" backend sh -c "pip install httpx && python -m unittest discover -s tests -v"
```

## Prepare the next milestones

The implementation checklist is in [TASKS.md](TASKS.md). Docker setup downloads assets only;
the worker uses downloaded voices and the tagged background catalog when rendering.
No downloads run automatically with the regular app startup.

### 1. Choose storage locations

Run from this project folder in PowerShell. If `.env` already exists, edit it instead of overwriting it.

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force D:/local-ai-video-generator/storage,D:/local-ai-video-generator/assets,D:/local-ai-video-generator/models
docker compose config --quiet
```

The example uses D: because C: has limited space. Edit `.env` to choose different folders.
Existing files under the project's `storage/` are not moved automatically when changing the mount.
Docker images and build caches still use Docker Desktop's configured disk location;
these paths only relocate app assets, models and outputs.

### 2. Download the two English speech voices

```powershell
docker compose --profile setup run --rm --no-deps asset-download voices
```

Downloads Piper lessac-medium and ryan-medium ONNX models, their configuration files,
and model cards under `assets/voices`. Each voice is approximately 63 MB.
Review the individual model cards for usage terms. This does not install or run Piper yet.

### 3. Download sample backgrounds

```powershell
docker compose --profile setup run --rm --no-deps asset-download backgrounds
```

`setup/backgrounds.json` contains one sample mountain background. Add more entries with
direct HTTPS image URLs, filename, tags, source, author, license and license URL.
The downloader saves a credits JSON next to each image. The sample is by Hannes Röst,
licensed CC BY-SA 3.0; preserve attribution and follow its license when distributing adaptations.
This is a catalog downloader, not automatic transcript-based online search.
Alternatively copy your own licensed images into `assets/backgrounds`.

Background setup always creates an original 1280x720 neutral gradient PNG locally.
If a remote image host rejects a request (for example Wikimedia HTTP 403), setup reports
the skipped image and keeps this fallback available. It does not label the gradient as
the missing photo. HTTP 403/404/429 responses are not immediately retried; rerun the
background command later or use your own image. Other successful downloads are preserved.

Both asset commands skip existing nonempty files, retry failed downloads and use temporary
files before finishing. To replace a damaged or changed asset, remove that specific file and rerun.

### 4. Optional transcript model

Skip this step if you want explicit scene/dialogue parsing only.

```powershell
docker compose --profile ai up -d ollama
docker compose --profile ai --profile setup run --rm model-download
docker compose --profile ai exec ollama ollama list
```

The default is `qwen2.5:1.5b` (approximately 986 MB download, more RAM needed at runtime).
Ollama runs on CPU with one model and one parallel request. Its API is internal to Docker;
the backend is configured to reach `http://ollama:11434`, but integration is a later task.
The setup profile alone does not start downloads: use the explicit `run` commands above.

### 5. Start the existing dashboard

```powershell
docker compose up --build -d backend frontend
```

To stop everything, including the optional model server:

```powershell
docker compose --profile ai --profile setup down
```

No image/video generation models are included: those are unsuitable for the detected integrated GPU.
Models and images require internet during the explicit download steps; downloaded assets remain on disk.
