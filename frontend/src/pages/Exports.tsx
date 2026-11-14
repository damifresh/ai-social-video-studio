import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, fmtBytes, fmtDuration } from '../lib/api';
import { Badge, Button, Empty, Panel, SectionTitle, Spinner, statusTone } from '../components/ui';

type ExportRow = {
  project_id: string;
  title: string;
  aspect_ratio: string;
  status: string;
  updated_at?: string;
  video_url: string | null;
  srt_url: string | null;
  duration_sec?: number | null;
  size_bytes?: number | null;
  peak_memory_mb?: number | null;
  renders: number;
  history: any[];
};

export default function Exports() {
  const [rows, setRows] = useState<ExportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [playing, setPlaying] = useState<string | null>(null);
  const [filter, setFilter] = useState('');

  const load = async () => {
    try {
      const r = await api.exports();
      setRows(r.exports || []);
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

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => r.title.toLowerCase().includes(q) || r.aspect_ratio.includes(q));
  }, [rows, filter]);

  const totals = useMemo(() => {
    const done = rows.filter((r) => r.video_url);
    return {
      count: done.length,
      seconds: done.reduce((n, r) => n + (r.duration_sec || 0), 0),
      bytes: done.reduce((n, r) => n + (r.size_bytes || 0), 0),
    };
  }, [rows]);

  const selected = rows.find((r) => r.project_id === playing);

  return (
    <div className="fade-in space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h1 className="text-[30px] font-semibold leading-tight tracking-tight text-white">Export center</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            Finished 720p videos, subtitle sidecars and render reports. Files stay on disk; download or re-open any project to iterate.
          </p>
        </div>
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter exports…" className="input max-w-xs" />
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Panel className="px-4 py-3.5">
          <div className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Rendered videos</div>
          <div className="mt-1 text-2xl font-semibold text-white">{totals.count}</div>
        </Panel>
        <Panel className="px-4 py-3.5">
          <div className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Total footage</div>
          <div className="mt-1 text-2xl font-semibold text-white">{fmtDuration(totals.seconds)}</div>
        </Panel>
        <Panel className="px-4 py-3.5">
          <div className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Disk used</div>
          <div className="mt-1 text-2xl font-semibold text-white">{fmtBytes(totals.bytes)}</div>
        </Panel>
      </div>

      {err && <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{err}</div>}

      {loading ? (
        <div className="flex items-center gap-3 text-sm text-slate-400"><Spinner /> Loading exports…</div>
      ) : visible.length === 0 ? (
        <Empty
          title="No exports yet"
          hint="Render a project and it will appear here with its MP4, subtitles and measured render report."
          action={<Link to="/new"><Button variant="primary">Create a video</Button></Link>}
        />
      ) : (
        <div className="space-y-3">
          {visible.map((r) => (
            <Panel key={r.project_id} className="overflow-hidden">
              <div className="flex flex-col gap-4 p-4 sm:flex-row">
                <div className="relative w-full shrink-0 overflow-hidden rounded-xl bg-slate-950 sm:w-[260px]">
                  {r.video_url ? (
                    <video
                      controls
                      preload="metadata"
                      poster={`/api/projects/${r.project_id}/files/thumbnail?v=${encodeURIComponent(r.updated_at || '')}`}
                      src={r.video_url}
                      className="aspect-video w-full"
                    />
                  ) : (
                    <div className="flex aspect-video items-center justify-center text-xs text-slate-500">No render</div>
                  )}
                </div>
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link to={`/project/${r.project_id}`} className="truncate text-[15px] font-medium text-slate-100 hover:text-white">{r.title}</Link>
                    <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                    <Badge tone="slate">{r.aspect_ratio}</Badge>
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
                    <span>{fmtDuration(r.duration_sec)}</span>
                    <span>{fmtBytes(r.size_bytes)}</span>
                    <span>{r.peak_memory_mb ? `${r.peak_memory_mb} MB peak` : 'peak —'}</span>
                    <span>{r.renders} render{r.renders === 1 ? '' : 's'}</span>
                    <span>{r.updated_at ? new Date(r.updated_at).toLocaleString() : ''}</span>
                  </div>
                  <div className="flex flex-wrap gap-2 pt-1">
                    {r.video_url && (
                      <a href={r.video_url} download className="inline-flex items-center rounded-xl bg-gradient-to-b from-indigo-500 to-indigo-600 px-3 py-1.5 text-xs font-medium text-white">Download MP4</a>
                    )}
                    {r.srt_url && <a href={r.srt_url} download className="inline-flex items-center rounded-xl border border-white/10 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/[0.06]">SRT</a>}
                    <a href={`/api/projects/${r.project_id}/files/vtt`} download className="inline-flex items-center rounded-xl border border-white/10 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/[0.06]">VTT</a>
                    <a href={`/api/projects/${r.project_id}/files/result`} target="_blank" rel="noreferrer" className="inline-flex items-center rounded-xl border border-white/10 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/[0.06]">Result JSON</a>
                    <Link to={`/project/${r.project_id}`} className="inline-flex items-center rounded-xl border border-white/10 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/[0.06]">Open project</Link>
                    {r.video_url && (
                      <button onClick={() => setPlaying(r.project_id)} className="inline-flex items-center rounded-xl border border-white/10 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-white/[0.06]">
                        Large preview
                      </button>
                    )}
                  </div>
                  {r.history?.length > 0 && (
                    <div className="pt-1 text-[10px] text-slate-600">
                      Last renders: {r.history.slice(-3).reverse().map((h, i) => (
                        <span key={i} className="mr-2">
                          {h.at ? new Date(h.at).toLocaleDateString() : '—'} · {fmtDuration(h.duration_sec)} · {fmtBytes(h.size_bytes)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </Panel>
          ))}
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6" onClick={() => setPlaying(null)}>
          <div className="w-full max-w-4xl space-y-2" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-white">{selected.title}</span>
              <button onClick={() => setPlaying(null)} className="rounded-lg px-2 py-1 text-xs text-slate-400 hover:bg-white/10 hover:text-white">Close ✕</button>
            </div>
            {selected.video_url && <video autoPlay controls src={selected.video_url} className="max-h-[75vh] w-full rounded-xl bg-black" />}
            <div className="flex flex-wrap gap-2">
              <a href={selected.video_url || '#'} download className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/[0.06]">Download MP4</a>
              <Link to={`/project/${selected.project_id}`} className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/[0.06]">Open project</Link>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
