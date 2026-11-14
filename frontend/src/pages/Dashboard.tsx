import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, fmtDuration, ProjectT } from '../lib/api';
import { Badge, Button, Empty, Panel, SectionTitle, statusTone } from '../components/ui';

const STYLES = [
  { id: 'cinematic', name: 'Cinematic', desc: 'Moody, story-led visuals' },
  { id: 'documentary', name: 'Documentary', desc: 'Measured, factual pacing' },
  { id: 'educational', name: 'Educational', desc: 'Clear structure, teaching tone' },
  { id: 'explainer', name: 'Explainer', desc: 'Simple, direct breakdowns' },
  { id: 'news', name: 'News', desc: 'Timely, headline-driven' },
  { id: 'motivational', name: 'Motivational', desc: 'Upbeat, forward motion' },
  { id: 'marketing', name: 'Marketing', desc: 'Persuasive, CTA-focused' },
  { id: 'faceless', name: 'Faceless Social', desc: 'Fast, caption-first' },
];

export default function Dashboard() {
  const [projects, setProjects] = useState<ProjectT[]>([]);
  const [err, setErr] = useState('');
  const [loading, setLoading] = useState(true);
  const nav = useNavigate();

  const load = async () => {
    try {
      const r = await api.projects();
      setProjects(r.projects);
      setErr('');
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const stats = useMemo(() => {
    const completed = projects.filter((p) => p.status === 'completed');
    const totalSec = completed.reduce((n, p) => n + (p.duration_sec || 0), 0);
    return { total: projects.length, completed: completed.length, minutes: totalSec / 60, drafts: projects.filter((p) => p.status === 'draft').length };
  }, [projects]);

  const recent = projects.slice(0, 6);
  const drafts = projects.filter((p) => p.status === 'draft' || p.status === 'failed' || p.status === 'interrupted');

  const duplicate = async (p: ProjectT) => {
    const r = await api.duplicateProject(p.id);
    nav(`/project/${r.project.id}`);
  };
  const remove = async (p: ProjectT) => {
    if (!confirm(`Delete “${p.title}”? Project artifacts stay on disk for recovery.`)) return;
    await api.deleteProject(p.id);
    load();
  };

  return (
    <div className="fade-in space-y-8">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-indigo-300/80">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" /> Local production studio
          </div>
          <h1 className="text-[30px] font-semibold leading-tight tracking-tight text-white">Dashboard</h1>
          <p className="mt-1 max-w-xl text-sm text-slate-400">
            Turn a topic into a finished 720p social video — script, storyboard, narration, subtitles, music and motion, rendered fully on this Mac.
          </p>
        </div>
        <Link to="/new">
          <Button variant="primary" className="px-4 py-2.5">
            <span className="text-base leading-none">＋</span> Create New Video
          </Button>
        </Link>
      </div>

      {err && <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{err}</div>}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Projects" value={String(stats.total)} hint="all time" />
        <Stat label="Completed" value={String(stats.completed)} hint="rendered videos" />
        <Stat label="Runtime" value={`${stats.minutes.toFixed(1)}m`} hint="finished footage" />
        <Stat label="In progress" value={String(projects.filter((p) => p.status === 'generating').length)} hint="generating now" />
      </div>

      <section>
        <SectionTitle
          title="Recent projects"
          subtitle="Reopen, duplicate or continue where you left off."
          right={<Link to="/exports" className="text-xs text-slate-400 hover:text-white">View exports →</Link>}
        />
        {loading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3].map((i) => <div key={i} className="h-48 animate-pulse rounded-2xl bg-white/[0.03]" />)}
          </div>
        ) : recent.length === 0 ? (
          <Empty
            title="No projects yet"
            hint="Start with a topic — the studio writes the script, storyboard and narration automatically."
            action={<Link to="/new"><Button variant="primary">Create your first video</Button></Link>}
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {recent.map((p) => (
              <ProjectCard key={p.id} p={p} onDuplicate={() => duplicate(p)} onDelete={() => remove(p)} />
            ))}
          </div>
        )}
      </section>

      {drafts.length > 0 && (
        <section>
          <SectionTitle title="Drafts & needs attention" subtitle="Drafts, failed or interrupted jobs — artifacts are always preserved." />
          <div className="space-y-2">
            {drafts.map((p) => (
              <Panel key={p.id} className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-slate-200">{p.title}</div>
                  <div className="text-xs text-slate-500">
                    {p.style} · {p.duration_min} min · {p.aspect_ratio} · updated {p.updated_at ? new Date(p.updated_at).toLocaleString() : '—'}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge tone={statusTone(p.status)}>{p.status}</Badge>
                  <Link to={`/project/${p.id}`}><Button variant="ghost">Open</Button></Link>
                </div>
              </Panel>
            ))}
          </div>
        </section>
      )}

      <section>
        <SectionTitle title="Templates" subtitle="Style presets — pick one to prefill a new project." />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {STYLES.map((s) => (
            <Link
              key={s.id}
              to={`/new?style=${s.id}`}
              className="group rounded-2xl border border-white/[0.07] bg-gradient-to-b from-white/[0.04] to-transparent p-4 transition hover:border-indigo-400/30 hover:from-indigo-500/[0.08]"
            >
              <div className="mb-6 h-1.5 w-10 rounded-full bg-gradient-to-r from-indigo-400 to-fuchsia-400 opacity-70" />
              <div className="text-sm font-medium text-slate-200 group-hover:text-white">{s.name}</div>
              <div className="mt-0.5 text-xs text-slate-500">{s.desc}</div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <Panel className="px-4 py-3.5">
      <div className="text-[11px] uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight text-white">{value}</div>
      <div className="text-[11px] text-slate-500">{hint}</div>
    </Panel>
  );
}

function ProjectCard({ p, onDuplicate, onDelete }: { p: ProjectT; onDuplicate: () => void; onDelete: () => void }) {
  return (
    <div className="group overflow-hidden rounded-2xl border border-white/[0.07] bg-slate-900/40 transition hover:border-white/[0.14]">
      <Link to={`/project/${p.id}`} className="block">
        <div className="relative aspect-video overflow-hidden bg-gradient-to-br from-slate-800 to-slate-950">
          {p.thumbnail ? (
            <img
              src={`/api/projects/${p.id}/files/thumbnail?v=${encodeURIComponent(p.updated_at || '')}`}
              alt=""
              className="h-full w-full object-cover opacity-80 transition group-hover:scale-[1.02] group-hover:opacity-100"
              onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-3xl text-slate-700">✦</div>
          )}
          <div className="absolute left-2 top-2"><Badge tone={statusTone(p.status)}>{p.status}</Badge></div>
          <div className="absolute bottom-2 right-2 rounded-md bg-black/60 px-1.5 py-0.5 text-[10px] text-slate-200 backdrop-blur">
            {p.aspect_ratio} · {fmtDuration(p.duration_sec)}
          </div>
        </div>
      </Link>
      <div className="space-y-2 p-3.5">
        <Link to={`/project/${p.id}`} className="block truncate text-sm font-medium text-slate-100 hover:text-white">{p.title}</Link>
        <div className="truncate text-xs text-slate-500">{p.topic || p.prompt || '—'}</div>
        <div className="flex items-center justify-between pt-1">
          <span className="text-[11px] text-slate-500">{p.style} · {p.duration_min} min</span>
          <div className="flex gap-1 opacity-70 transition group-hover:opacity-100">
            <button onClick={onDuplicate} title="Duplicate" className="rounded-lg px-2 py-1 text-[11px] text-slate-400 hover:bg-white/[0.06] hover:text-white">Copy</button>
            <button onClick={onDelete} title="Delete" className="rounded-lg px-2 py-1 text-[11px] text-slate-400 hover:bg-rose-500/15 hover:text-rose-300">Delete</button>
          </div>
        </div>
      </div>
    </div>
  );
}
