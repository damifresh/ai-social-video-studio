import { useEffect, useState } from 'react'
import { api } from '../lib/api'

export default function Settings() {
  const [health, setHealth] = useState<any>(null)
  const [voices, setVoices] = useState<any[]>([])
  useEffect(()=>{ api.health().then(setHealth).catch(()=>{}); api.voices().then(d=>setVoices(d.voices||[])).catch(()=>{}) }, [])
  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-3xl font-semibold">Settings & System</h1>
      <div className="rounded-xl border border-slate-800 p-5 space-y-2">
        <h2 className="font-medium">Runtime</h2>
        <pre className="text-xs text-slate-300 whitespace-pre-wrap">{JSON.stringify(health, null, 2)}</pre>
        <p className="text-sm text-slate-400">FFmpeg must be available. Generation runs sequentially (max 1 job) to respect 8 GB unified memory.</p>
      </div>
      <div className="rounded-xl border border-slate-800 p-5 space-y-2">
        <h2 className="font-medium">Voices</h2>
        <ul className="text-sm text-slate-300 space-y-1 max-h-64 overflow-auto">{voices.map(v=><li key={v.id}>• <b>{v.name}</b> <span className="text-slate-500">({v.engine}, {v.lang}) {v.note?`— ${v.note}`:''}</span></li>)}</ul>
      </div>
      <div className="rounded-xl border border-slate-800 p-5 space-y-2 text-sm text-slate-300">
        <h2 className="font-medium">Notes</h2>
        <ul className="list-disc pl-5 space-y-1">
          <li>Output: 720p MP4 (H.264/AAC), 30 FPS, 9:16 / 16:9 / 1:1.</li>
          <li>Visuals default to <b>animated graphics/motion scenes</b> (Ken Burns/zoompan). Diffusion video models are experimental and not assumed feasible on 8 GB.</li>
          <li>Kokoro TTS requires separate MLX-compatible install (Python 3.10+). macOS `say` is the always-available local fallback.</li>
          <li>Subtitles: SRT/VTT generated from narration timings; whisper.cpp alignment can be added when installed.</li>
          <li>No paid APIs, no cloud inference, no subscriptions required.</li>
        </ul>
      </div>
    </div>
  )
}
