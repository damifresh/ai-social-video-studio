import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, fmtBytes } from '../lib/api';
import { Badge, Button, Empty, Panel, SectionTitle, Spinner } from '../components/ui';

const FILTERS = [
  { id: '', label: 'All media' },
  { id: 'image', label: 'Images' },
  { id: 'audio', label: 'Narration' },
  { id: 'music', label: 'Music' },
  { id: 'sfx', label: 'SFX' },
  { id: 'video', label: 'Video' },
  { id: 'subtitle', label: 'Subtitles' },
];

type Item = {
  kind: string;
  name: string;
  rel?: string;
  url: string;
  size: number;
  project_id: string | null;
  project_title: string;
  aspect_ratio?: string;
};

export default function Library() {
  const [filter, setFilter] = useState('');
  const [items, setItems] = useState<Item[]>([]);
  const [bundled, setBundled] = useState<Item[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  const load = async (kind = filter) => {
    setLoading(true);
    try {
      const r = await api.library(kind || undefined);
      setItems(r.items || []);
      setBundled(r.bundled || []);
      setErr('');
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load(filter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const match = (i: Item) => !q || i.name.toLowerCase().includes(q) || (i.project_title || '').toLowerCase().includes(q);
    return { items: items.filter(match), bundled: bundled.filter(match) };
  }, [items, bundled, query]);

  return (
    <div className="fade-in space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h1 className="text-[30px] font-semibold leading-tight tracking-tight text-white">Asset library</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            Every image, narration clip, render and subtitle file the studio has produced — plus bundled licensed music and SFX.
          </p>
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search files or projects…"
          className="input max-w-xs"
        />
      </div>

      <div className="flex flex-wrap gap-1 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-1.5">
        {FILTERS.map((f) => (
          <button key={f.id} onClick={() => setFilter(f.id)} className={`tab ${filter === f.id ? 'tab-active' : ''}`}>
            {f.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 pr-1 text-[11px] text-slate-500">
          {loading ? <Spinner /> : `${visible.items.length + visible.bundled.length} files`}
        </div>
      </div>

      {err && <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{err}</div>}

      {!loading && visible.items.length === 0 && visible.bundled.length === 0 && (
        <Empty
          title="Nothing matches"
          hint="Generate a video first, or drop files into assets/music and assets/sfx with a licenses.json entry."
          action={<Link to="/new"><Button variant="primary">Create a video</Button></Link>}
        />
      )}

      {visible.bundled.length > 0 && (
        <section>
          <SectionTitle title="Bundled library" subtitle="Music and SFX shipped with the studio. Check assets/music/licenses.json before publishing." />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {visible.bundled.map((i) => (
              <Panel key={i.url} className="space-y-2 p-3.5">
                <div className="flex items-center justify-between gap-2">
                  <Badge tone={i.kind === 'music' ? 'indigo' : 'violet'}>{i.kind}</Badge>
                  <span className="text-[10px] text-slate-500">{fmtBytes(i.size)}</span>
                </div>
                <div className="truncate text-sm text-slate-200">{i.name}</div>
                <audio controls preload="none" src={i.url} className="h-8 w-full" />
              </Panel>
            ))}
          </div>
        </section>
      )}

      {visible.items.length > 0 && (
        <section>
          <SectionTitle title="Project media" subtitle="Files live in each project folder and are not deleted when a project is removed (unless you ask)." />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {visible.items.map((i) => (
              <Panel key={`${i.project_id}-${i.rel}`} className="overflow-hidden">
                {i.kind === 'image' ? (
                  <a href={i.url} target="_blank" rel="noreferrer" className="block aspect-video overflow-hidden bg-slate-950">
                    <img src={i.url} alt={i.name} className="h-full w-full object-cover opacity-85 transition hover:opacity-100" loading="lazy" />
                  </a>
                ) : i.kind === 'video' ? (
                  <video controls preload="metadata" src={i.url} className="aspect-video w-full bg-black" />
                ) : i.kind === 'subtitle' ? (
                  <div className="flex aspect-video items-center justify-center bg-slate-950/70 text-3xl text-slate-700">CC</div>
                ) : (
                  <div className="flex flex-col justify-center gap-1 bg-slate-950/40 px-3 py-4">
                    <audio controls preload="none" src={i.url} className="h-8 w-full" />
                  </div>
                )}
                <div className="space-y-1.5 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-medium text-slate-200">{i.name}</span>
                    <Badge tone="slate">{i.kind}</Badge>
                  </div>
                  <div className="flex items-center justify-between gap-2 text-[10px] text-slate-500">
                    <Link to={`/project/${i.project_id}`} className="truncate hover:text-slate-300">{i.project_title}</Link>
                    <span className="shrink-0">{fmtBytes(i.size)}</span>
                  </div>
                  <div className="flex items-center gap-2 pt-1">
                    <a href={i.url} download className="rounded-lg border border-white/10 px-2 py-1 text-[10px] text-slate-300 hover:bg-white/[0.06]">Download</a>
                    <a href={i.url} target="_blank" rel="noreferrer" className="rounded-lg border border-white/10 px-2 py-1 text-[10px] text-slate-300 hover:bg-white/[0.06]">Open</a>
                    {i.rel && <span className="ml-auto truncate font-mono text-[9px] text-slate-600">{i.rel}</span>}
                  </div>
                </div>
              </Panel>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
