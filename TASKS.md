# Implementation tasks

Task 1 is configured. Project persistence and character/dialogue editing (tasks 2–3)
are implemented, with explicit transcript parsing and basic scene review/reordering
from tasks 4 and 7. Speech generation, local background matching/fallback, single-worker
rendering, progress, cancellation, preview and download are now implemented.
Model-based scene planning, lip-sync, advanced animation and selective scene retries remain planned.

1. **Prepare assets (configured; user runs downloads).** Set storage paths, download two English Piper voices and one credited sample background; optionally pull Qwen 2.5 1.5B. Done when files exist and `ollama list` shows the model.
2. **Project persistence (implemented).** Project title, transcript, characters and scenes are stored in SQLite; uploaded media stays in project folders. Job status comes with the render worker.
3. **Characters and dialogue (implemented).** Named characters, validated image uploads, voice selection, editable dialogue, save/reopen and unknown-speaker validation.
4. **Scene planning.** Start with explicit scene headings and dialogue parsing. Add optional Qwen extraction into validated JSON: location, mood, background tags, characters and dialogue. Require review of inferred settings. Done when malformed model output can be corrected without losing user text.
5. **Background selection (basic implementation).** Render-time tag matching against the downloaded catalog, procedural jungle/neutral fallback and exported credits. Per-scene photo upload/override and selection previews remain planned.
6. **Speech generation (implemented; Docker rebuild required).** Piper runtime in the worker, selected voice per dialogue line and measured WAV durations. Cross-render audio caching remains planned.
7. **Storyboard editor.** Edit/reorder scenes, characters and dialogue; preview layout and timings. Done when editing one line invalidates only the affected speech/render assets.
8. **Render worker (implemented).** Single CPU worker, SQLite queue, snapshot isolation, restart from beginning, errors and progress. Character cards, background, subtitles and speech assembled into 720p MP4. Pan/zoom remains planned.
9. **Delivery and verification (basic implementation).** Preview/download, cancel and regenerate, successful-job intermediate cleanup. Automated tests cover real FFmpeg output with stub speech; actual Piper synthesis requires the downloaded models and rebuilt Docker worker. Selective scene retries and failed-job cleanup UI remain planned.

## Later, after the first working video

- Transparent character cutouts and expressions.
- Lip-sync with a separately evaluated CPU/GPU workflow.
- Optional remote GPU image/video generation; no large diffusion/video model download in this setup.
- Additional languages and voice models after the required languages are confirmed.

## Hardware limits

Use one generation/render job at a time. Start at 720p, 24 fps and short scenes.
RAM is still unverified. Try deterministic scene parsing first if the optional model causes memory pressure.
Qwen 1.5B is a small draft assistant: validate its output and let users correct it.
