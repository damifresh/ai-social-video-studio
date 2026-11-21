import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { clipApi, ClipCapabilitiesT, ClipProjectT, fmtBytes, fmtDuration } from '../lib/api';
import { Alert, Badge, Button, Empty, Field, Panel, SectionTitle, Spinner, statusTone } from '../components/ui';
import Prompter from '../components/Prompter';

const ASPECTS = [
  { id: '9:16', label: '9:16 Vertical', hint: 'TikTok, Reels, Shorts' },
  { id: '16:9', label: '16:9 Landscape', hint: 'YouTube, web' },
  { id: '1:1', label: '1:1 Square', hint: 'Feed posts' },
];

const LANGUAGES = [
  ['en', 'English'],
  ['auto', 'Auto detect'],
  ['es', 'Spanish'],
  ['fr', 'French'],
  ['de', 'German'],
  ['pt', 'Portuguese'],
  ['it', 'Italian'],
  ['hi', 'Hindi'],
  ['ja', 'Japanese'],
  ['ko', 'Korean'],
  ['zh', 'Chinese'],
];

export default function ClipStudio() {
  const nav = useNavigate();
  const [caps, setCaps] = useState<ClipCapabilitiesT | null>(null);
  const [projects, setProjects] = useState<ClipProjectT[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [aspect, setAspect] = useState('9:16');
  const [language, setLanguage] = useState('en');
  const [prompt, setPrompt] = useState('');
  const [directorPreset, setDirectorPreset] = useState('tiktok');
  const [singleClip, setSingleClip] = useState(false);
  const [captions, setCaptions] = useState(true);
  const [transitions, setTransitions] = useState(true);

  const load = async () => {
    try {
      const [c, p] = await Promise.all([clipApi.capabilities(), clipApi.projects()]);
      setCaps(c);
      setProjects(p.projects);
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

  const preset = useMemo(() => {
    if (!caps) return 'tiktok';
    const hit = Object.entries(caps.presets).find(([, v]) => v.aspect === aspect);
    return hit ? hit[0] : 'tiktok';
  }, [caps, aspect]);

  const create = async () => {
    setCreating(true);
    try {
      const r = await clipApi.createProject({
        title: title.trim() || 'Untitled clip project',
        aspect_ratio: aspect,
        preset,
        director_preset: directorPreset,
        single_clip: singleClip,
        burn_captions: captions,
        transitions,
        language,
        prompt,
      });
      nav(`/clip/${r.project.id}`);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setCreating(false);
    }
  };

  const asr = caps?.asr;

  return (
    <div className="space-y-6">
      <SectionTitle
        title="AI Auto-Clip Studio"
        subtitle="Turn one long recording — or several videos combined into one — into short, captioned vertical clips, fully local."
        right={
          <Badge tone="violet">Engine B · local only</Badge>
        }
      />

      {err && <Alert>{err}</Alert>}

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-2">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-[15px] font-semibold text-white">New clip project</h2>
              <p className="mt-1 text-[12px] text-slate-400">
                Upload an MP4/MOV/MKV/WebM recording, or several videos to combine into one seamless output.
                Original files are stored untouched; hashes and stream metadata are recorded for audit.
              </p>
            </div>
            <Badge tone="slate">720p output</Badge>
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label="Project title">
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Podcast episode 42"
                className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-3 py-2 text-[13px] text-slate-100 outline-none placeholder:text-slate-600 focus:border-indigo-400/50"
              />
            </Field>
            <Field label="Spoken language" hint="Used by whisper.cpp; import is unaffected">
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-3 py-2 text-[13px] text-slate-100 outline-none focus:border-indigo-400/50"
              >
                {LANGUAGES.map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <div className="mt-4">
            <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">Aspect ratio</div>
            <div className="grid gap-2 sm:grid-cols-3">
              {ASPECTS.map((a) => (
                <button
                  key={a.id}
                  onClick={() => setAspect(a.id)}
                  className={`rounded-xl border px-3 py-2.5 text-left transition ${
                    aspect === a.id
                      ? 'border-indigo-400/40 bg-indigo-500/10 text-white'
                      : 'border-white/10 bg-white/[0.02] text-slate-300 hover:border-white/20'
                  }`}
                >
                  <div className="text-[13px] font-medium">{a.label}</div>
                  <div className="text-[11px] text-slate-500">{a.hint}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="mt-5 flex items-center gap-3">
            <Button variant="primary" onClick={create} disabled={creating}>
              {creating ? <Spinner /> : null}
              Create project
            </Button>
            <span className="text-[11px] text-slate-500">
              Storage: local <code className="rounded bg-white/5 px-1">data/clip_projects/</code>
            </span>
          </div>
        </Panel>

        <Panel>
          <h2 className="text-[15px] font-semibold text-white">Local capabilities</h2>
          <div className="mt-3 space-y-2.5 text-[12px]">
            <div className="flex items-start justify-between gap-2">
              <span className="text-slate-400">Speech recognition</span>
              {asr?.available ? (
                <Badge tone="green">{asr.backend}</Badge>
              ) : (
                <Badge tone="amber">unavailable</Badge>
              )}
            </div>
            {!asr?.available && (
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5 text-[11px] leading-relaxed text-amber-200/90">
                {asr?.reasons?.length
                  ? asr.reasons.join(' · ')
                  : 'No local ASR backend detected.'}
                <div className="mt-1 text-amber-200/70">
                  Use <strong>Transcript → Import SRT/VTT</strong>, or run{' '}
                  <code className="rounded bg-black/30 px-1">scripts/install_whisper_cpp.sh</code>. Transcripts are
                  never invented.
                </div>
              </div>
            )}
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Manual transcript import</span>
              <Badge tone="green">always on</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Reframing</span>
              <Badge tone="slate">manual crop</Badge>
            </div>
            <p className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5 text-[11px] leading-relaxed text-slate-400">
              No face or subject tracking is implemented. Crops are deterministic geometry: centred cover-crop, or a
              manual rectangle you position yourself.
            </p>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Standalone ffprobe</span>
              <Badge tone={caps?.diagnostics?.ffprobe_standalone ? 'green' : 'slate'}>
                {caps?.diagnostics?.ffprobe_standalone ? 'ffprobe' : 'ffmpeg fallback'}
              </Badge>
            </div>
          </div>
        </Panel>
      </div>

      <Prompter
        value={prompt}
        onChange={setPrompt}
        preset={directorPreset}
        onPresetChange={setDirectorPreset}
        singleClip={singleClip}
        onSingleClipChange={setSingleClip}
        captions={captions}
        onCaptionsChange={setCaptions}
        transitions={transitions}
        onTransitionsChange={setTransitions}
      />

      <Panel>
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-semibold text-white">Clip projects</h2>
          <Button variant="subtle" onClick={load}>
            Refresh
          </Button>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-8 text-[13px] text-slate-400">
            <Spinner /> Loading…
          </div>
        ) : projects.length === 0 ? (
          <div className="mt-4">
            <Empty
              title="No clip projects yet"
              hint="Create one above, then upload a recording to transcribe and auto-clip."
            />
          </div>
        ) : (
          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {projects.map((p) => (
              <Link
                key={p.id}
                to={`/clip/${p.id}`}
                className="group rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5 transition hover:border-indigo-400/30 hover:bg-white/[0.04]"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-[13px] font-semibold text-slate-100">{p.title}</div>
                    <div className="mt-0.5 truncate text-[11px] text-slate-500">
                      {p.source ? p.source.original_name : 'no source yet'}
                    </div>
                  </div>
                  <Badge tone={statusTone(p.status)}>{p.status}</Badge>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                  <div>
                    Source <span className="text-slate-200">{fmtDuration(p.source?.duration_sec || 0)}</span>
                  </div>
                  <div>
                    Frame{' '}
                    <span className="text-slate-200">
                      {p.source ? `${p.source.width}×${p.source.height}` : '—'}
                    </span>
                  </div>
                  <div>
                    Clips <span className="text-slate-200">{p.counts.clips}</span>
                  </div>
                  <div>
                    Renders <span className="text-slate-200">{p.counts.rendered}</span>
                  </div>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-slate-500">
                  <span className="rounded bg-white/5 px-1.5 py-0.5">{p.aspect_ratio}</span>
                  <span className="rounded bg-white/5 px-1.5 py-0.5">{p.preset}</span>
                  <span className="rounded bg-white/5 px-1.5 py-0.5">
                    {p.transcript?.present ? `transcript · ${p.transcript.backend}` : 'no transcript'}
                  </span>
                  {p.source && (
                    <span className="rounded bg-white/5 px-1.5 py-0.5">{fmtBytes(p.source.size_bytes)}</span>
                  )}
                </div>
                {p.error && <div className="mt-2 truncate text-[11px] text-rose-300">{p.error}</div>}
              </Link>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
