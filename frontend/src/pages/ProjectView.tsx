import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../lib/api'

export default function ProjectView() {
  const { id } = useParams()
  const [data, setData] = useState<any>(null)
  const [job, setJob] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [tab, setTab] = useState<'script'|'storyboard'|'render'|'export'>('script')
  const [scriptText, setScriptText] = useState('')
  const pollRef = useRef<any>(null)

  const load = async () => {
    if (!id) return
    try { const d = await api.project(id); setData(d); if(d.script) setScriptText(JSON.stringify(d.script, null, 2)); } catch(e:any){ setErr(String(e)) }
  }
  useEffect(()=>{ load(); return ()=>{ if(pollRef.current) clearInterval(pollRef.current) } }, [id])

  const startPoll = (jobId: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async ()=>{
      try {
        const j = await api.job(jobId); setJob(j.job)
        if (['succeeded','failed','canceled'].includes(j.job.status)) { clearInterval(pollRef.current); pollRef.current=null; load() }
      } catch {}
    }, 1500)
  }

  const act = async (fn: ()=>Promise<any>, label: string) => {
    setBusy(true); setErr(''); setMsg(label+'...')
    try { const r = await fn(); setMsg(label+' done'); if(r?.job){ setJob(r.job); startPoll(r.job.id) } else { load() } }
    catch(e:any){ setErr(String(e.message||e)); setMsg('') } finally { setBusy(false) }
  }

  const saveScript = async () => {
    try { const obj = JSON.parse(scriptText); await api.saveScript(id!, obj); setMsg('Script saved'); load() } catch(e:any){ setErr('Invalid JSON or save failed: '+String(e.message||e)) }
  }

  if (!id) return <div>Missing project id</div>
  if (!data) return <div>Loading... {err && <span className="text-red-400">{err}</span>}</div>
  const p = data.project
  const scenes = data.scenes || data.script?.scenes || []
  const result = data.result

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{p.title}</h1>
          <div className="text-sm text-slate-400">{p.topic} · {p.duration_min} min · {p.aspect_ratio} · {p.style} · <span className="text-slate-300">{p.status}</span></div>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button disabled={busy} onClick={()=>act(()=>api.generateScript(id!), 'Script generation')} className="btn">Generate Script</button>
          <button disabled={busy} onClick={()=>act(()=>api.generate(id!), 'Full generation')} className="btn-primary">Generate Full Video</button>
        </div>
      </div>
      {(msg || err) && <div className={`text-sm ${err?'text-red-400':'text-emerald-400'}`}>{err || msg}</div>}
      {job && (
        <div className="rounded-xl border border-slate-800 p-4 bg-slate-900/40">
          <div className="flex justify-between text-sm mb-2"><span>Job: {job.status} · {job.stage}</span><span>{job.progress || 0}%</span></div>
          <div className="w-full h-2 bg-slate-800 rounded"><div className="h-2 bg-indigo-500 rounded" style={{width:`${job.progress||0}%`}} /></div>
          <div className="text-xs text-slate-400 mt-2">{job.message}</div>
          {job.error && <div className="text-xs text-red-400 mt-1 whitespace-pre-wrap">{job.error}</div>}
          <div className="text-xs text-slate-500 mt-1">Real progress from backend job state (sequential pipeline).</div>
        </div>
      )}

      <div className="flex gap-2 border-b border-slate-800 pb-2">
        {(['script','storyboard','render','export'] as const).map(t=> <button key={t} onClick={()=>setTab(t)} className={`px-3 py-1.5 rounded text-sm ${tab===t?'bg-slate-800 text-white':'text-slate-400 hover:text-white'}`}>{t[0].toUpperCase()+t.slice(1)}</button>)}
      </div>

      {tab==='script' && (
        <div className="space-y-3">
          <p className="text-sm text-slate-400">Edit the generated script/scene JSON directly, or regenerate. Save before full render to use edits.</p>
          <textarea value={scriptText} onChange={e=>setScriptText(e.target.value)} className="w-full min-h-[420px] bg-slate-950 border border-slate-800 rounded-lg p-3 font-mono text-xs" />
          <div className="flex gap-2"><button onClick={saveScript} className="btn-primary">Save Script JSON</button><button onClick={load} className="btn">Reload</button></div>
        </div>
      )}
      {tab==='storyboard' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-400">Scene-by-scene storyboard. Regenerate an individual scene without rebuilding the whole project (re-render final to apply).</p>
          {scenes.length===0 ? <div className="text-slate-500">No scenes yet. Generate script first.</div> : scenes.map((sc:any, i:number)=> (
            <div key={i} className="rounded-xl border border-slate-800 p-4 bg-slate-900/40">
              <div className="flex justify-between items-start gap-2">
                <div className="font-medium">Scene {i+1}: {sc.title||''} <span className="text-xs text-slate-500">({sc.duration_sec||sc.render_dur||'?'}s · {sc.camera||'motion'} · {sc.transition||'cut'})</span></div>
                <button disabled={busy} onClick={()=>act(()=>api.regenScene(id!, i), `Regenerate scene ${i+1}`)} className="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700">Regenerate Scene</button>
              </div>
              <div className="mt-2 text-sm"><b>Narration:</b> {sc.narration}</div>
              <div className="mt-1 text-sm text-slate-300"><b>Visual:</b> {sc.visual_description}</div>
              <div className="mt-1 text-xs text-slate-400"><b>Overlay:</b> {sc.text_overlay} · <b>SFX:</b> {sc.sfx} · <b>Kind:</b> {sc.visual_kind || 'animated_graphic (planned)'}</div>
            </div>
          ))}
        </div>
      )}
      {tab==='render' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-400">Sequential pipeline: script → storyboard → visuals → TTS → subtitles → audio mix → per-scene render → final compose. On 8 GB, heavy steps run one at a time.</p>
          <div className="rounded-xl border border-slate-800 p-4 space-y-2 text-sm">
            <div><b>Voice:</b> {p.voice} {scenes[0]?.tts_fallback ? <span className="text-amber-400">(fallback used: {scenes[0].tts_fallback})</span> : null}</div>
            <div><b>Subtitles:</b> {p.subtitle_enabled ? 'enabled (SRT/VTT)' : 'disabled'}</div>
            <div><b>Output:</b> 720p MP4 H.264/AAC, 30fps, {p.aspect_ratio}</div>
            <div><b>Visual mode:</b> animated graphics/motion (honest default). Generated footage only if explicitly produced and labeled.</div>
          </div>
          <button disabled={busy} onClick={()=>act(()=>api.generate(id!), 'Full generation')} className="btn-primary">Run Full Pipeline</button>
        </div>
      )}
      {tab==='export' && (
        <div className="space-y-4">
          {result?.final_video ? (
            <div className="space-y-3">
              <div className="text-sm text-slate-300">Final render ready: {result.duration_sec ? `${Math.round(result.duration_sec)}s` : ''} · {result.aspect_ratio} · 720p</div>
              <video controls className="w-full max-w-3xl rounded-xl border border-slate-800 bg-black" src={api.fileUrl(id!, 'video')} />
              <div className="flex gap-2 flex-wrap text-sm">
                <a className="btn-primary" href={api.fileUrl(id!, 'video')} download>Download MP4</a>
                <a className="btn" href={api.fileUrl(id!, 'srt')} download>Download SRT</a>
                <a className="btn" href={api.fileUrl(id!, 'vtt')} download>Download VTT</a>
                <a className="btn" href={api.fileUrl(id!, 'result')} target="_blank">Result JSON</a>
              </div>
            </div>
          ) : <div className="text-slate-400">No completed render yet. Run the full pipeline first.</div>}
        </div>
      )}
    </div>
  )
}
