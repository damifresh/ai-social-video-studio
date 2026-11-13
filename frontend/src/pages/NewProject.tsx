import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'

export default function NewProject() {
  const nav = useNavigate()
  const [form, setForm] = useState<any>({ title:'', topic:'', prompt:'', duration_min:1, aspect_ratio:'16:9', style:'cinematic', language:'en', voice:'say:Samantha', subtitle_enabled:true, music_track:'none' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const set = (k:string,v:any)=> setForm((f:any)=>({...f,[k]:v}))
  const submit = async (e:any) => {
    e.preventDefault(); setBusy(true); setErr('')
    try {
      const r = await api.createProject({ ...form, title: form.title || form.topic || 'Untitled' })
      nav(`/project/${r.project.id}`)
    } catch(e:any){ setErr(String(e.message||e)) } finally { setBusy(false) }
  }
  return (
    <div className="max-w-3xl space-y-6">
      <div><h1 className="text-3xl font-semibold">New Project</h1><p className="text-slate-400">Define your video. Generation runs locally and sequentially (8GB-safe).</p></div>
      {err && <div className="text-red-400 text-sm">{err}</div>}
      <form onSubmit={submit} className="space-y-5">
        <Field label="Video Title"><input className="inp" value={form.title} onChange={e=>set('title',e.target.value)} placeholder="e.g. Morning Routines That Work" /></Field>
        <Field label="Topic"><input className="inp" value={form.topic} onChange={e=>set('topic',e.target.value)} placeholder="Main topic" required /></Field>
        <Field label="Detailed Prompt"><textarea className="inp min-h-[100px]" value={form.prompt} onChange={e=>set('prompt',e.target.value)} placeholder="Tone, key points, audience, CTA..." /></Field>
        <div className="grid md:grid-cols-3 gap-4">
          <Field label="Duration"><select className="inp" value={form.duration_min} onChange={e=>set('duration_min',Number(e.target.value))}>{[1,2,3,4,5].map(m=><option key={m} value={m}>{m} minute{m>1?'s':''}</option>)}</select></Field>
          <Field label="Aspect Ratio"><select className="inp" value={form.aspect_ratio} onChange={e=>set('aspect_ratio',e.target.value)}>{['9:16','16:9','1:1'].map(v=><option key={v}>{v}</option>)}</select></Field>
          <Field label="Resolution"><select className="inp" value="720p" disabled><option>720p</option></select></Field>
        </div>
        <div className="grid md:grid-cols-2 gap-4">
          <Field label="Style"><select className="inp" value={form.style} onChange={e=>set('style',e.target.value)}>{['cinematic','documentary','educational','explainer','news','motivational','marketing','faceless'].map(v=><option key={v} value={v}>{v}</option>)}</select></Field>
          <Field label="Voice"><select className="inp" value={form.voice} onChange={e=>set('voice',e.target.value)}><option value="say:Samantha">Samantha (macOS, local)</option><option value="say:Alex">Alex (macOS, local)</option><option value="say:Daniel">Daniel (macOS, local)</option><option value="say:Karen">Karen (macOS, local)</option><option value="kokoro:af_heart">Kokoro af_heart (if installed)</option></select></Field>
        </div>
        <div className="grid md:grid-cols-2 gap-4">
          <Field label="Narration Language"><input className="inp" value={form.language} onChange={e=>set('language',e.target.value)} /></Field>
          <Field label="Subtitles"><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.subtitle_enabled} onChange={e=>set('subtitle_enabled',e.target.checked)} /> Enable automatic subtitles (SRT/VTT)</label></Field>
        </div>
        <Field label="Background Music"><select className="inp" value={form.music_track} onChange={e=>set('music_track',e.target.value)}><option value="none">None (voice only)</option></select><div className="text-xs text-slate-500 mt-1">Add properly licensed audio files to assets/music and select in settings/editor (MVP: none bundled by default).</div></Field>
        <button disabled={busy} className="px-5 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50">{busy?'Creating...':'Create Project'}</button>
      </form>
    </div>
  )
}
function Field({label,children}:{label:string,children:any}){
  return <div><label className="block text-sm text-slate-300 mb-1">{label}</label>{children}</div>
}
// quick global input style via class
