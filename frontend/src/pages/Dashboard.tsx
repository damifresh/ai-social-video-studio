import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

export default function Dashboard() {
  const [projects, setProjects] = useState<any[]>([])
  const [err, setErr] = useState('')
  const load = () => api.projects().then(d=>setProjects(d.projects||[])).catch(e=>setErr(String(e)))
  useEffect(()=>{ load() }, [])
  const recent = projects.slice(0,6)
  const drafts = projects.filter(p=>p.status==='draft')
  const done = projects.filter(p=>p.status==='completed')
  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div><h1 className="text-3xl font-semibold">Dashboard</h1><p className="text-slate-400">Local AI Social Video Studio · 8GB-safe sequential pipeline</p></div>
        <Link to="/new" className="px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500">Create New Video</Link>
      </div>
      {err && <div className="text-red-400 text-sm">{err}</div>}
      <div className="grid grid-cols-3 gap-4">
        <Stat label="Total Projects" value={projects.length} />
        <Stat label="Drafts" value={drafts.length} />
        <Stat label="Completed" value={done.length} />
      </div>
      <Section title="Recent Projects" items={recent} onRefresh={load} />
      <Section title="Draft Projects" items={drafts} onRefresh={load} />
      <Section title="Completed Videos" items={done} onRefresh={load} />
      <div className="rounded-xl border border-slate-800 p-5">
        <h2 className="font-medium mb-2">Video Templates</h2>
        <p className="text-sm text-slate-400">Styles: Cinematic, Documentary, Educational, Explainer, News, Motivational, Marketing, Faceless. Select a style when creating a new project.</p>
      </div>
    </div>
  )
}
function Stat({label,value}:{label:string,value:number}){
  return <div className="rounded-xl border border-slate-800 p-4 bg-slate-900/40"><div className="text-slate-400 text-sm">{label}</div><div className="text-2xl font-semibold">{value}</div></div>
}
function Section({title,items,onRefresh}:{title:string,items:any[],onRefresh:()=>void}){
  return (
    <div>
      <div className="flex items-center justify-between mb-3"><h2 className="text-lg font-medium">{title}</h2><button onClick={onRefresh} className="text-sm text-slate-400 hover:text-white">Refresh</button></div>
      {items.length===0 ? <div className="text-sm text-slate-500">No projects yet.</div> : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map(p=> <Card key={p.id} p={p} onRefresh={onRefresh} />)}
        </div>
      )}
    </div>
  )
}
function Card({p,onRefresh}:{p:any,onRefresh:()=>void}){
  const del = async()=>{ if(confirm('Delete project?')){ await api.deleteProject(p.id); onRefresh() } }
  const dup = async()=>{ await api.duplicateProject(p.id); onRefresh() }
  return (
    <div className="rounded-xl border border-slate-800 p-4 bg-slate-900/40 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-medium">{p.title||'Untitled'}</div>
          <div className="text-xs text-slate-400">{p.style} · {p.duration_min} min · {p.aspect_ratio} · {p.status}</div>
        </div>
        <span className={`text-xs px-2 py-1 rounded ${p.status==='completed'?'bg-emerald-900/50 text-emerald-300':p.status==='failed'?'bg-red-900/50 text-red-300':p.status==='generating'?'bg-amber-900/50 text-amber-300':'bg-slate-800 text-slate-300'}`}>{p.status}</span>
      </div>
      <div className="text-sm text-slate-300 line-clamp-2">{p.topic||p.prompt||'—'}</div>
      <div className="flex gap-2 text-sm">
        <Link to={`/project/${p.id}`} className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700">Open</Link>
        <button onClick={dup} className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700">Duplicate</button>
        <button onClick={del} className="px-3 py-1.5 rounded bg-slate-800 hover:bg-red-900/40">Delete</button>
      </div>
    </div>
  )
}
