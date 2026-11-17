import { useEffect, useState } from 'react'

type Job = { id: string; status: string; progress: number; message: string }
const base = `${window.location.protocol}//${window.location.hostname}:8000/api`
async function request(path: string, method = 'GET') {
  const response = await fetch(base + path, { method })
  const value = await response.json()
  if (!response.ok) throw new Error(value.detail || 'Request failed')
  return value
}

export default function RenderPanel({ projectId, dirty }: { projectId?: string; dirty: boolean }) {
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  const [statusError, setStatusError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!projectId) return
    let active = true
    async function refresh() {
      try {
        const latest = await request(`/projects/${projectId}/renders/latest`)
        if (active) { setJob(latest); setStatusError('') }
      } catch (e) { if (active) setStatusError(e instanceof Error ? e.message : 'Cannot check rendering status') }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 2500)
    return () => { active = false; window.clearInterval(timer) }
  }, [projectId])
  const running = job?.status === 'queued' || job?.status === 'running'
  async function generate() {
    setBusy(true); setError('')
    try { setJob(await request(`/projects/${projectId}/renders`, 'POST')) }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not start generation') }
    finally { setBusy(false) }
  }
  return <section>
    <div className="section-heading"><div><h2>4. Video with speech</h2><p className="hint">720p · character images · assigned voices · subtitles</p></div>
      <button className="primary" disabled={!projectId || dirty || running || busy} onClick={() => void generate()}>{running ? 'Generating…' : 'Generate video with speech'}</button></div>
    {(!projectId || dirty) && <p className="hint">Save your project before generating. Each speaking character needs an uploaded image.</p>}
    <p className="hint">Matching local background photos are used when available. Jungle/forest descriptions get a simple illustrated jungle fallback. This version uses still character images; it does not animate mouths.</p>
    {(error || statusError) && <div className="notice error" role="alert">{error || statusError}</div>}
    {job && <div className="render-status" aria-live="polite">
      <strong>{job.status.charAt(0).toUpperCase() + job.status.slice(1)} · {job.progress}%</strong>
      <progress max={100} value={job.progress} aria-label="Video generation progress" />
      <p className="hint">{job.message}</p>
      {job.status === 'queued' && <p className="hint">If this stays queued, start the worker: docker compose up --build -d worker</p>}
      {running && <button onClick={async () => { try { setJob(await request(`/renders/${job.id}/cancel`, 'POST')) } catch (e) { setError(String(e)) } }}>Cancel generation</button>}
      {job.status === 'completed' && <>
        <video key={job.id} controls preload="metadata" src={`${base}/renders/${job.id}/video`} />
        <div className="actions"><a className="download-link" href={`${base}/renders/${job.id}/video?download=true`}>Download MP4</a><a href={`${base}/renders/${job.id}/credits`}>Background credits</a></div>
        <p className="hint">This video uses the saved project and images from when generation started. Generate again to include later edits.</p>
      </>}
    </div>}
  </section>
}
