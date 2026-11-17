import { useEffect, useState } from 'react'
import RenderPanel from './RenderPanel'

type Character = { id: string; name: string; voice: string }
type Line = { character_id: string; text: string }
type Scene = { title: string; background: string; dialogue: Line[] }
type Project = { id?: string; title: string; transcript: string; characters: Character[]; scenes: Scene[] }
type Summary = { id: string; title: string; updated_at: string }
const base = `${window.location.protocol}//${window.location.hostname}:8000`
const blank = (): Project => ({ title: 'Untitled project', transcript: '', characters: [], scenes: [] })
const id = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')
async function api(path: string, options?: RequestInit) {
  const response = await fetch(base + '/api' + path, options)
  const data = await response.json()
  if (!response.ok) {
    const detail = data.detail
    throw new Error(Array.isArray(detail) ? detail.map(x => typeof x === 'string' ? x : x.msg).join('\n') : detail || 'Request failed')
  }
  return data
}
const json = (method: string, value: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) })

export default function App() {
  const [project, setProject] = useState<Project>(blank)
  const [projects, setProjects] = useState<Summary[]>([])
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [imageVersion, setImageVersion] = useState(0)
  const [online, setOnline] = useState(false)
  useEffect(() => { api('/projects').then(setProjects).catch(e => setError(e.message)); api('/health').then(() => setOnline(true)).catch(() => setOnline(false)) }, [])
  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])
  function change(next: Project) { setProject(next); setDirty(true); setMessage(''); setError('') }
  async function action(work: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('')
    try { await work() } catch (e) { setError(e instanceof Error ? e.message : 'Something went wrong') } finally { setBusy(false) }
  }
  async function save() {
    const saved = await api(project.id ? `/projects/${project.id}` : '/projects', json(project.id ? 'PUT' : 'POST', project))
    setProject(saved); setDirty(false)
    setProjects(await api('/projects'))
    setMessage('Project saved. You can reopen it from the project list.')
    return saved as Project
  }
  function newProject() {
    if (dirty && !window.confirm('Discard unsaved changes?')) return
    setProject(blank()); setDirty(false); setMessage(''); setError('')
  }
  function editCharacter(index: number, update: Partial<Character>) {
    change({ ...project, characters: project.characters.map((c, i) => i === index ? { ...c, ...update } : c) })
  }
  function editScene(index: number, update: Partial<Scene>) {
    change({ ...project, scenes: project.scenes.map((s, i) => i === index ? { ...s, ...update } : s) })
  }
  function moveScene(index: number, offset: number) {
    const scenes = [...project.scenes]
    ;[scenes[index], scenes[index + offset]] = [scenes[index + offset], scenes[index]]
    change({ ...project, scenes })
  }
  return <main className="shell">
    <header><div><div className="eyebrow">LOCAL VIDEO STUDIO</div><h1>Build your story.</h1><p>Give your characters a voice. Shape each scene before rendering.</p></div><span className="status">{online ? 'API connected' : 'API unavailable'}</span></header>
    <div className="layout">
      <aside><div className="section-heading"><h2>Projects</h2><button onClick={newProject} disabled={busy}>+ New</button></div>
        {projects.length === 0 && <p className="hint">Saved projects appear here.</p>}
        {projects.map(p => <button key={p.id} className={`project-link ${p.id === project.id ? 'selected' : ''}`} disabled={busy} onClick={() => {
          if (dirty && !window.confirm('Discard unsaved changes?')) return
          void action(async () => { setProject(await api(`/projects/${p.id}`)); setDirty(false); setImageVersion(Date.now()) })
        }}>{p.title}<small>{new Date(p.updated_at).toLocaleString()}</small></button>)}
      </aside>
      <fieldset disabled={busy} className="editor">
        <div className="toolbar"><label className="grow">Project title<input value={project.title} maxLength={200} onChange={e => change({ ...project, title: e.target.value })} /></label><button className="primary" onClick={() => void action(async () => { await save() })}>{busy ? 'Working…' : 'Save project'}</button><span className="hint">{dirty ? 'Unsaved changes' : project.id ? 'Saved' : 'New project'}</span></div>
        {error && <div className="notice error" role="alert">{error}</div>}{message && <div className="notice" role="status">{message}</div>}
        <section><div className="section-heading"><div><h2>1. Characters</h2><p className="hint">Add a name and voice, then upload a reference image. Uploading also saves your project.</p></div><button disabled={project.characters.length >= 30} onClick={() => change({ ...project, characters: [...project.characters, { id: id(), name: `Character ${project.characters.length + 1}`, voice: 'en_US-lessac-medium' }] })}>+ Character</button></div>
          <div className="characters">{project.characters.map((c, index) => <article key={c.id} className="character">
            <div className="portrait"><img key={`${project.id}-${c.id}-${imageVersion}`} src={project.id ? `${base}/api/projects/${project.id}/characters/${c.id}/image?v=${imageVersion}` : undefined} alt={`${c.name} reference`} onError={e => { e.currentTarget.style.display = 'none' }} /><span>Reference image</span></div>
            <label>Name<input value={c.name} maxLength={80} onChange={e => editCharacter(index, { name: e.target.value })} /></label>
            <label>Voice<select value={c.voice} onChange={e => editCharacter(index, { voice: e.target.value })}><option value="en_US-lessac-medium">Lessac · English</option><option value="en_US-ryan-medium">Ryan · English</option></select></label>
            <label className="upload">Upload image<input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => {
              const file = e.target.files?.[0]; e.target.value = ''; if (!file) return
              if (file.size > 10 * 1024 * 1024) { setError('Image must be 10 MB or smaller'); return }
              void action(async () => {
                const saved = await save()
                await api(`/projects/${saved.id}/characters/${c.id}/image`, { method: 'POST', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file })
                setImageVersion(Date.now()); setMessage('Character image saved.')
              })
            }} /></label><small className="hint">PNG, JPEG or WebP · up to 10 MB</small>
            <button className="text-button" onClick={() => {
              if (project.scenes.some(s => s.dialogue.some(l => l.character_id === c.id))) { setError('Reassign or remove this character’s dialogue first.'); return }
              change({ ...project, characters: project.characters.filter(x => x.id !== c.id) })
            }}>Remove character</button>
          </article>)}</div>
          {!project.characters.length && <p className="empty">Add your first character to start writing dialogue.</p>}
        </section>
        <section><div className="section-heading"><h2>2. Transcript</h2><button onClick={() => {
          if (project.scenes.length && !window.confirm('Replace the current scene edits with a new transcript draft?')) return
          void action(async () => { const result = await api('/parse', json('POST', project)); change({ ...project, scenes: result.scenes }); setMessage('Scene draft ready. Review it below, then save your project.') })
        }}>Build scene draft</button></div>
          <p className="hint">Use # for scene headings, Background: for the setting, and exact character names before dialogue. Drafting replaces scene edits; it does not save automatically.</p>
          <textarea className="transcript" value={project.transcript} maxLength={100000} placeholder={'# A morning walk\nBackground: A quiet park in daylight\nAli: Shall we take a walk?\nSara: Yes, let’s go.'} onChange={e => change({ ...project, transcript: e.target.value })} />
        </section>
        <section><div className="section-heading"><div><h2>3. Scene review</h2><p className="hint">Edit settings and dialogue independently of the source transcript.</p></div><button onClick={() => change({ ...project, scenes: [...project.scenes, { title: `Scene ${project.scenes.length + 1}`, background: '', dialogue: [] }] })}>+ Scene</button></div>
          {!project.scenes.length && <p className="empty">Build a scene draft from the transcript, or add a scene manually.</p>}
          {project.scenes.map((s, index) => <article className="scene" key={index}>
            <div className="section-heading"><strong>Scene {index + 1}</strong><div className="actions"><button disabled={index === 0} onClick={() => moveScene(index, -1)} aria-label="Move scene up">↑</button><button disabled={index === project.scenes.length - 1} onClick={() => moveScene(index, 1)} aria-label="Move scene down">↓</button><button onClick={() => change({ ...project, scenes: project.scenes.filter((_, i) => i !== index) })}>Remove</button></div></div>
            <label>Scene title<input value={s.title} maxLength={200} onChange={e => editScene(index, { title: e.target.value })} /></label>
            <label>Background / theme description<input value={s.background} maxLength={1000} placeholder="Location, time of day and mood" onChange={e => editScene(index, { background: e.target.value })} /></label>
            {s.dialogue.map((line, lineIndex) => <div className="dialogue" key={lineIndex}><label>Speaker<select value={line.character_id} onChange={e => editScene(index, { dialogue: s.dialogue.map((l, i) => i === lineIndex ? { ...l, character_id: e.target.value } : l) })}>{project.characters.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}</select></label><label className="grow">Dialogue<textarea value={line.text} maxLength={5000} onChange={e => editScene(index, { dialogue: s.dialogue.map((l, i) => i === lineIndex ? { ...l, text: e.target.value } : l) })} /></label><button aria-label="Remove dialogue" onClick={() => editScene(index, { dialogue: s.dialogue.filter((_, i) => i !== lineIndex) })}>×</button></div>)}
            <button disabled={!project.characters.length} onClick={() => editScene(index, { dialogue: [...s.dialogue, { character_id: project.characters[0].id, text: '' }] })}>+ Dialogue</button>
          </article>)}
        </section>
        <RenderPanel key={project.id || 'new'} projectId={project.id} dirty={dirty} />
        <footer>Videos are generated locally. Save changes before creating a new version.</footer>
      </fieldset>
    </div>
  </main>
}
