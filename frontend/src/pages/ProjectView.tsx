import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  api,
  CueT,
  fmtBytes,
  fmtDuration,
  JobT,
  ProjectDetailT,
  SceneT,
} from '../lib/api';
import { useJob } from '../lib/hooks';
import {
  Alert,
  Badge,
  Button,
  Empty,
  Field,
  Panel,
  Progress,
  SectionTitle,
  Spinner,
  statusTone,
} from '../components/ui';

type Tab = 'script' | 'storyboard' | 'timeline' | 'voice' | 'subtitles' | 'assets' | 'export';

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: 'script', label: 'Script', hint: 'Narration and scene text' },
  { id: 'storyboard', label: 'Storyboard', hint: 'Scenes, visuals, motion' },
  { id: 'timeline', label: 'Timeline', hint: 'Timing, transitions, mix' },
  { id: 'voice', label: 'Voice', hint: 'Narration engine' },
  { id: 'subtitles', label: 'Subtitles', hint: 'Cues and styling' },
  { id: 'assets', label: 'Assets', hint: 'Project media' },
  { id: 'export', label: 'Export', hint: 'Render and download' },
];

const CAMERAS = ['slow_zoom_in', 'slow_zoom_out', 'slow_pan_left', 'slow_pan_right', 'pan_up', 'pan_down', 'static'];
const TRANSITIONS = ['cut', 'fade', 'fadeblack', 'crossfade'];

function clock(sec?: number | null): string {
  const s = Math.max(0, Number(sec || 0));
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(1).padStart(4, '0')}`;
}

function sceneDur(sc: SceneT): number {
  return Number(sc.render_dur || sc.actual_audio_dur || sc.duration_sec || 5);
}

function sceneImageUrl(pid: string, sc: SceneT, idx: number, cache = ''): string {
  const raw = sc.image_path || '';
  const marker = '/images/';
  const rel = raw.includes(marker)
    ? 'images/' + (raw.split(marker).pop() as string)
    : `images/scene_${String(idx + 1).padStart(2, '0')}.png`;
  return api.assetUrl(pid, rel) + (cache ? `?v=${encodeURIComponent(cache)}` : '');
}

function sceneAudioUrl(pid: string, sc: SceneT): string | null {
  const raw = sc.audio_path || '';
  const marker = '/audio/';
  if (!raw.includes(marker)) return null;
  return api.assetUrl(pid, 'audio/' + (raw.split(marker).pop() as string));
}

export default function ProjectView() {
  const { id } = useParams();
  const pid = id || '';
  const [data, setData] = useState<ProjectDetailT | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [notice, setNotice] = useState('');
  const [tab, setTab] = useState<Tab>('script');
  const [scenes, setScenes] = useState<SceneT[]>([]);
  const [dirty, setDirty] = useState(false);
  const [cues, setCues] = useState<CueT[]>([]);
  const [style, setStyle] = useState<Record<string, any>>({});
  const [voices, setVoices] = useState<any[]>([]);
  const [bundledMusic, setBundledMusic] = useState<any[]>([]);
  const [jobs, setJobs] = useState<JobT[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState('');
  const [assets, setAssets] = useState<{ images: any[]; audio: any[]; other: any[] } | null>(null);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewing, setPreviewing] = useState('');
  const [imgVersion, setImgVersion] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const load = useCallback(async () => {
    if (!pid) return;
    try {
      const d = await api.project(pid);
      setData(d);
      setScenes(d.scenes || []);
      setCues(d.subtitles || []);
      setStyle(d.project.subtitle_style || {});
      setDirty(false);
      setErr('');
      api.projectJobs(pid).then((r) => setJobs(r.jobs)).catch(() => {});
      api.projectAssets(pid).then(setAssets).catch(() => {});
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [pid]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    api.voices().then((r) => setVoices(r.voices || [])).catch(() => {});
    api.music().then((r) => setBundledMusic(r.tracks || [])).catch(() => {});
  }, []);

  const { job } = useJob(jobId, (j) => {
    if (j.status === 'succeeded') setNotice(j.message || 'Job completed.');
    if (j.status === 'failed') setErr(j.error || 'Job failed.');
    load();
  });

  useEffect(() => {
    if (job && job.status !== 'running' && job.status !== 'queued') load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status]);

  useEffect(() => {
    if (jobId || !jobs.length) return;
    const live = jobs.find((j) => j.status === 'running' || j.status === 'queued');
    if (live) setJobId(live.id);
  }, [jobs, jobId]);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const p = data?.project;
  const result = data?.result;
  const cache = p?.updated_at || '';

  const timings = useMemo(() => {
    let cursor = 0;
    return scenes.map((sc, i) => {
      const dur = sceneDur(sc);
      const row = { start: cursor, end: cursor + dur, dur, index: i };
      cursor += dur;
      return row;
    });
  }, [scenes]);
  const totalDur = timings.length ? timings[timings.length - 1].end : 0;

  const updateScene = (i: number, patch: Partial<SceneT>) => {
    setScenes((prev) => prev.map((sc, idx) => (idx === i ? { ...sc, ...patch } : sc)));
    setDirty(true);
    setNotice('');
  };

  const saveScenes = async (silent = false): Promise<boolean> => {
    if (!pid || !data) return false;
    try {
      setBusy('save');
      const body = {
        ...(data.script || {}),
        scenes,
        scene_count: scenes.length,
        full_text: scenes.map((s) => s.narration || '').join('\n\n'),
      };
      await api.saveScript(pid, body);
      setDirty(false);
      setData((d) => (d ? { ...d, script: body, scenes } : d));
      if (!silent) setNotice('Script and storyboard saved.');
      return true;
    } catch (e: any) {
      setErr(String(e.message || e));
      return false;
    } finally {
      setBusy('');
    }
  };

  const runJob = async (fn: () => Promise<{ job: JobT }>, label: string) => {
    if (!pid) return;
    setErr('');
    setNotice('');
    try {
      const r = await fn();
      setJobId(r.job.id);
      setJobs((j) => [r.job, ...j]);
      setNotice(`${label} started.`);
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  };

  const generateScript = async () => {
    if (!pid) return;
    if (!confirm('Generate a fresh script? Current scene text and storyboard edits will be replaced.')) return;
    setBusy('script');
    setErr('');
    setNotice('');
    try {
      await api.generateScript(pid);
      await load();
      setNotice('New script generated. Review the scenes, then render.');
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy('');
    }
  };

  const fullRender = async () => {
    if (dirty && !(await saveScenes(true))) return;
    await runJob(() => api.generate(pid), 'Full pipeline');
    setTab('export');
  };

  const rerender = async () => {
    if (dirty && !(await saveScenes(true))) return;
    await runJob(() => api.rerender(pid, p?.burn_subs), 'Re-render');
    setTab('export');
  };

  const regenScene = async (i: number) => {
    if (dirty && !(await saveScenes(true))) return;
    await runJob(() => api.regenScene(pid, i), `Scene ${i + 1} regeneration`);
  };

  const uploadSceneImage = async (i: number, file: File) => {
    setErr('');
    try {
      setBusy(`image-${i}`);
      await api.uploadSceneImage(pid, i, file);
      setImgVersion((v) => v + 1);
      await load();
      setNotice(`Scene ${i + 1} now uses your uploaded image.`);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy('');
    }
  };

  const moveScene = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= scenes.length) return;
    setScenes((prev) => {
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next.map((sc, idx) => ({ ...sc, index: idx }));
    });
    setDirty(true);
  };

  const patchProject = async (patch: Record<string, any>, msg?: string) => {
    if (!pid) return;
    setErr('');
    try {
      const r = await api.updateProject(pid, patch);
      setData((d) => (d ? { ...d, project: r.project } : d));
      if (msg) setNotice(msg);
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  };

  const previewVoice = async (voice: string, text?: string) => {
    setErr('');
    setPreviewing(voice);
    try {
      const url = await api.previewVoice(voice, text);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      setPreviewUrl(url);
      setTimeout(() => audioRef.current?.play().catch(() => {}), 60);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setPreviewing('');
    }
  };

  const saveSubtitles = async () => {
    if (!pid) return;
    setBusy('subs');
    setErr('');
    try {
      const clean = cues
        .filter((c) => (c.text || '').trim())
        .map((c) => ({ ...c, start: Number(c.start), end: Math.max(Number(c.end), Number(c.start) + 0.2) }))
        .sort((a, b) => a.start - b.start);
      await api.saveSubtitles(pid, clean, style);
      await load();
      setNotice('Subtitle files rebuilt (SRT, VTT, ASS). Re-render to burn the new cues into the MP4.');
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy('');
    }
  };

  const startPreview = async () => {
    if (!pid) return;
    try {
      await api.saveSubtitles(pid, cues.filter((c) => (c.text || '').trim()), style);
      setStyle((s) => ({ ...s, customized: true }));
      await load();
      setNotice('Subtitle preview cues saved.');
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  };

  if (!pid) return <Alert>Missing project id.</Alert>;
  if (loading && !data) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-400">
        <Spinner /> Loading project…
      </div>
    );
  }
  if (!data || !p) return <Alert>{err || 'Project not found.'}</Alert>;

  const activeJob = job || jobs[0];
  const running = activeJob?.status === 'running' || activeJob?.status === 'queued';
  const canCancel = activeJob && (activeJob.status === 'running' || activeJob.status === 'queued');
  const jobMeta = activeJob?.meta || result || {};
  const sceneTts = scenes.find((s) => s.tts_fallback);

  return (
    <div className="fade-in space-y-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Link to="/" className="text-xs text-slate-500 hover:text-slate-300">
              ← Dashboard
            </Link>
            <span className="text-slate-700">/</span>
            <Badge tone={statusTone(p.status)}>{p.status}</Badge>
            {dirty && <Badge tone="amber">unsaved edits</Badge>}
            <Badge tone="slate">{p.aspect_ratio}</Badge>
            <Badge tone="slate">{p.fps} fps</Badge>
            <Badge tone="slate">720p</Badge>
          </div>
          <h1 className="truncate text-[26px] font-semibold leading-tight tracking-tight text-white">{p.title}</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            {p.topic || p.prompt || 'No topic'} · {p.duration_min} min target · {p.style} · scene audio drives final timing
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button onClick={generateScript} disabled={!!busy || running}>
            {busy === 'script' ? <Spinner /> : null} Regenerate script
          </Button>
          <Button onClick={rerender} disabled={running || !scenes.length}>
            Re-render
          </Button>
          <Button variant="primary" onClick={fullRender} disabled={running}>
            {running ? <Spinner /> : null} Generate full video
          </Button>
        </div>
      </div>

      {err && (
        <div className="flex items-start justify-between gap-3">
          <Alert>{err}</Alert>
          <button onClick={() => setErr('')} className="mt-1 text-xs text-slate-500 hover:text-white">
            dismiss
          </button>
        </div>
      )}
      {notice && !err && (
        <div className="flex items-start justify-between gap-3">
          <Alert tone="green">{notice}</Alert>
          <button onClick={() => setNotice('')} className="mt-1 text-xs text-slate-500 hover:text-white">
            dismiss
          </button>
        </div>
      )}

      {activeJob && (
        <Panel className="space-y-2.5 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2 text-sm">
              <Badge tone={statusTone(activeJob.status)}>{activeJob.status}</Badge>
              <span className="truncate text-slate-300">{activeJob.message || activeJob.stage}</span>
            </div>
            <div className="flex items-center gap-3 text-xs text-slate-500">
              {activeJob.elapsed_sec != null && <span>{activeJob.elapsed_sec.toFixed(1)} s elapsed</span>}
              {activeJob.eta_sec != null && activeJob.status === 'running' && <span>~{activeJob.eta_sec.toFixed(0)} s left</span>}
              {activeJob.peak_memory_mb ? <span>peak {activeJob.peak_memory_mb} MB</span> : null}
              <span>{activeJob.progress || 0}%</span>
              {canCancel && (
                <button
                  onClick={() => api.cancelJob(activeJob.id).then(() => setNotice('Cancellation requested — the pipeline stops at the next safe step.')).catch(() => {})}
                  className="rounded-lg border border-rose-500/30 px-2 py-1 text-rose-300 hover:bg-rose-500/10"
                >
                  Cancel
                </button>
              )}
            </div>
          </div>
          <Progress value={activeJob.progress || 0} />
          {activeJob.status === 'running' && <div className="text-[11px] text-slate-500">Stage: {activeJob.stage} · jobs run one at a time on this 8 GB Mac.</div>}
          {activeJob.error && <div className="whitespace-pre-wrap rounded-lg bg-rose-500/5 px-2 py-1 text-[11px] text-rose-300">{activeJob.error}</div>}
        </Panel>
      )}

      <div className="flex flex-wrap gap-1 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-1.5">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            title={t.hint}
            className={`tab ${tab === t.id ? 'tab-active' : ''}`}
          >
            {t.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 pr-1 text-[11px] text-slate-500">
          {scenes.length} scenes · {fmtDuration(totalDur)}
        </div>
      </div>

      {tab === 'script' && (
        <div className="space-y-4">
          <Panel className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="text-xs text-slate-400">
              <span className="text-slate-500">Generator:</span> {data.script?.generator || 'deterministic-local'}
              <span className="mx-2 text-slate-700">·</span>
              <span className="text-slate-500">Words:</span> {data.script?.word_count ?? scenes.reduce((n, s) => n + (s.narration || '').split(/\s+/).length, 0)}
              <span className="mx-2 text-slate-700">·</span>
              <span className="text-slate-500">Target:</span> {p.duration_min} min
            </div>
            <div className="flex gap-2">
              <Button onClick={() => saveScenes()} disabled={!dirty || busy === 'save'}>
                {busy === 'save' ? <Spinner /> : null} Save script
              </Button>
              <Button onClick={generateScript} disabled={!!busy || running}>
                Generate new script
              </Button>
            </div>
          </Panel>

          {scenes.length === 0 ? (
            <Empty
              title="No script yet"
              hint="Generate a script to get a scene-by-scene narration plan you can edit."
              action={<Button variant="primary" onClick={generateScript} disabled={!!busy}>Generate script</Button>}
            />
          ) : (
            <div className="space-y-3">
              {scenes.map((sc, i) => (
                <Panel key={i} className="space-y-2.5 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="flex h-6 min-w-6 items-center justify-center rounded-lg bg-white/[0.06] px-1.5 text-[11px] font-semibold text-slate-300">{i + 1}</span>
                      <input
                        className="input max-w-[260px] py-1.5 text-[13px]"
                        value={sc.title || ''}
                        onChange={(e) => updateScene(i, { title: e.target.value })}
                        placeholder="Scene title"
                      />
                    </div>
                    <div className="flex items-center gap-2 text-[11px] text-slate-500">
                      <span>{sceneDur(sc).toFixed(1)} s planned</span>
                      <span className="text-slate-700">·</span>
                      <span>{(sc.narration || '').split(/\s+/).filter(Boolean).length} words</span>
                      <Button variant="subtle" className="px-2 py-1 text-[11px]" onClick={() => regenScene(i)} disabled={running}>
                        Regenerate
                      </Button>
                    </div>
                  </div>
                  <textarea
                    className="textarea min-h-[110px] text-[13px]"
                    value={sc.narration || ''}
                    onChange={(e) => updateScene(i, { narration: e.target.value })}
                    placeholder="Narration for this scene — this is what the voice speaks and what subtitles are built from."
                  />
                </Panel>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'storyboard' && (
        <div className="space-y-4">
          <Panel className="flex flex-wrap items-center justify-between gap-3 p-4">
            <p className="max-w-xl text-xs leading-relaxed text-slate-400">
              Visuals are honest <span className="text-slate-200">animated graphics</span> (Pillow compositing + FFmpeg zoom/pan),
              not generated footage. Replace any scene image with your own still, or label generated footage explicitly if you add it.
            </p>
            <Button onClick={() => saveScenes()} disabled={!dirty || busy === 'save'}>
              {busy === 'save' ? <Spinner /> : null} Save storyboard
            </Button>
          </Panel>

          {scenes.length === 0 ? (
            <Empty title="No scenes" hint="Generate a script first, then edit the storyboard." />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {scenes.map((sc, i) => (
                <Panel key={i} className="overflow-hidden">
                  <div className="relative aspect-video bg-slate-950">
                    <img
                      src={sceneImageUrl(pid, sc, i, `${cache}-${imgVersion}-${sc.image_path || ''}`)}
                      alt={`Scene ${i + 1}`}
                      className="h-full w-full object-cover"
                      onError={(e) => ((e.target as HTMLImageElement).style.opacity = '0.12')}
                    />
                    <div className="absolute left-2 top-2 flex gap-1.5">
                      <Badge tone="indigo">Scene {i + 1}</Badge>
                      <Badge tone={sc.visual_kind === 'user_uploaded' ? 'amber' : 'slate'}>{sc.visual_kind || 'animated_graphic'}</Badge>
                    </div>
                    <div className="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 text-[10px] text-slate-200 backdrop-blur">
                      {sceneDur(sc).toFixed(1)} s
                    </div>
                    <div className="absolute bottom-2 left-2 flex gap-1">
                      <button
                        onClick={() => moveScene(i, -1)}
                        disabled={i === 0}
                        className="rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-slate-200 backdrop-blur disabled:opacity-30"
                        title="Move earlier"
                      >
                        ↑
                      </button>
                      <button
                        onClick={() => moveScene(i, 1)}
                        disabled={i === scenes.length - 1}
                        className="rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-slate-200 backdrop-blur disabled:opacity-30"
                        title="Move later"
                      >
                        ↓
                      </button>
                      <label className="cursor-pointer rounded-md bg-black/60 px-1.5 py-0.5 text-[11px] text-slate-200 backdrop-blur hover:bg-black/80">
                        Replace image
                        <input
                          type="file"
                          accept="image/png,image/jpeg,image/webp"
                          className="hidden"
                          onChange={(e) => {
                            const f = e.target.files?.[0];
                            if (f) uploadSceneImage(i, f);
                            e.target.value = '';
                          }}
                        />
                      </label>
                    </div>
                  </div>
                  <div className="space-y-2.5 p-3.5">
                    <div className="text-[13px] font-medium text-slate-200">{sc.title || `Scene ${i + 1}`}</div>
                    <div className="line-clamp-2 text-[11px] leading-relaxed text-slate-500">{sc.narration}</div>
                    <div className="grid grid-cols-2 gap-2">
                      <Field label="Camera motion">
                        <select className="select py-1.5 text-xs" value={sc.camera || 'slow_zoom_in'} onChange={(e) => updateScene(i, { camera: e.target.value })}>
                          {CAMERAS.map((c) => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
                        </select>
                      </Field>
                      <Field label="Transition">
                        <select className="select py-1.5 text-xs" value={sc.transition || 'cut'} onChange={(e) => updateScene(i, { transition: e.target.value })}>
                          {TRANSITIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                        </select>
                      </Field>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <Field label="Text overlay">
                        <input className="input py-1.5 text-xs" value={sc.text_overlay || ''} onChange={(e) => updateScene(i, { text_overlay: e.target.value })} />
                      </Field>
                      <Field label="SFX cue">
                        <input className="input py-1.5 text-xs" value={sc.sfx || 'none'} onChange={(e) => updateScene(i, { sfx: e.target.value })} placeholder="none" />
                      </Field>
                    </div>
                    <div className="flex items-center justify-between pt-1">
                      <span className="text-[10px] text-slate-600">TTS: {sc.tts_engine || 'pending'}{sc.tts_fallback ? ` · fallback from ${sc.tts_fallback}` : ''}</span>
                      <Button variant="subtle" className="px-2 py-1 text-[11px]" onClick={() => regenScene(i)} disabled={running}>
                        Regenerate scene
                      </Button>
                    </div>
                  </div>
                </Panel>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'timeline' && (
        <div className="space-y-4">
          <Panel className="space-y-4 p-5">
            <SectionTitle
              title="Timeline"
              subtitle="Scene length follows the real narration audio. Transitions are per-scene fades applied at render time."
              right={<span className="text-xs text-slate-500">{fmtDuration(totalDur)} total · {scenes.length} scenes</span>}
            />
            {scenes.length === 0 ? (
              <div className="text-sm text-slate-500">Generate a script to build a timeline.</div>
            ) : (
              <>
                <div className="relative h-16 overflow-hidden rounded-xl border border-white/[0.06] bg-slate-950/60">
                  {timings.map((t) => {
                    const left = (t.start / Math.max(totalDur, 0.001)) * 100;
                    const width = (t.dur / Math.max(totalDur, 0.001)) * 100;
                    return (
                      <div
                        key={t.index}
                        className="absolute top-0 flex h-full items-end border-r border-black/40 px-1.5 pb-1.5"
                        style={{
                          left: `${left}%`,
                          width: `${width}%`,
                          background: `linear-gradient(180deg, hsl(${(t.index * 47) % 360} 60% 32% / 0.45), hsl(${(t.index * 47) % 360} 60% 22% / 0.9))`,
                        }}
                        title={`Scene ${t.index + 1}: ${clock(t.start)} → ${clock(t.end)}`}
                      >
                        <span className="truncate text-[10px] font-medium text-white/80">{t.index + 1}</span>
                      </div>
                    );
                  })}
                </div>
                <div className="grid gap-1.5">
                  {timings.map((t) => (
                    <div key={t.index} className="flex items-center gap-3 rounded-lg border border-white/[0.05] bg-white/[0.02] px-3 py-1.5 text-xs">
                      <span className="w-6 text-slate-500">{t.index + 1}</span>
                      <span className="w-20 font-mono text-[11px] text-slate-300">{clock(t.start)}</span>
                      <span className="w-20 font-mono text-[11px] text-slate-500">{clock(t.end)}</span>
                      <span className="w-16 text-slate-400">{t.dur.toFixed(1)} s</span>
                      <span className="flex-1 truncate text-slate-500">{scenes[t.index].title || scenes[t.index].narration?.slice(0, 60)}</span>
                      <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-slate-400">{(scenes[t.index].transition || 'cut')}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel className="space-y-4 p-5">
              <h3 className="text-sm font-semibold text-slate-200">Render settings</h3>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Frame rate">
                  <select className="select" value={p.fps} onChange={(e) => patchProject({ fps: Number(e.target.value) }, 'Frame rate updated — re-render to apply.')}>
                    <option value={30}>30 fps</option>
                    <option value={24}>24 fps</option>
                  </select>
                </Field>
                <Field label="Format">
                  <input className="input opacity-70" value={`${p.aspect_ratio} · 720p`} disabled />
                </Field>
              </div>
              <label className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2.5">
                <span className="text-sm text-slate-300">Burn subtitles into video</span>
                <input
                  type="checkbox"
                  checked={!!p.burn_subs}
                  onChange={(e) => patchProject({ burn_subs: e.target.checked }, 'Subtitle burn-in updated — re-render to apply.')}
                  className="h-4 w-4 accent-indigo-500"
                />
              </label>
              <Field label="Aspect ratio" hint="Changing aspect requires a full re-render at the new dimensions.">
                <select className="select" value={p.aspect_ratio} onChange={(e) => patchProject({ aspect_ratio: e.target.value }, 'Aspect ratio updated — re-render to apply.')}>
                  <option value="16:9">16:9 · 1280×720</option>
                  <option value="9:16">9:16 · 720×1280</option>
                  <option value="1:1">1:1 · 720×720</option>
                </select>
              </Field>
            </Panel>

            <Panel className="space-y-4 p-5">
              <h3 className="text-sm font-semibold text-slate-200">Music & mix</h3>
              <Field label="Background track" hint="Music ducks under narration via sidechain compression, then a limiter protects peaks.">
                <select className="select" value={p.music_track} onChange={(e) => patchProject({ music_track: e.target.value }, 'Music track updated — re-render to apply.')}>
                  <option value="none">None — narration only</option>
                  {bundledMusic.filter((m) => m.kind === 'music').map((m) => (
                    <option key={m.name} value={m.name}>{m.name}</option>
                  ))}
                  {(assets?.audio || [])
                    .filter((a) => a.rel?.startsWith('assets/music/'))
                    .map((a) => (
                      <option key={a.rel} value={a.name}>{a.name} (project)</option>
                    ))}
                </select>
              </Field>
              <Field label={`Music level: ${Math.round((p.music_volume || 0) * 100)}%`}>
                <input
                  type="range"
                  min={0}
                  max={0.5}
                  step={0.01}
                  value={p.music_volume}
                  onChange={(e) => setData((d) => (d ? { ...d, project: { ...d.project, music_volume: Number(e.target.value) } } : d))}
                  onMouseUp={(e) => patchProject({ music_volume: Number((e.target as HTMLInputElement).value) })}
                  onTouchEnd={(e) => patchProject({ music_volume: Number((e.target as HTMLInputElement).value) })}
                  className="w-full"
                />
              </Field>
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[11px] leading-relaxed text-slate-500">
                Bundle tracks live in <span className="font-mono text-slate-400">assets/music</span> with a{' '}
                <span className="font-mono text-slate-400">licenses.json</span> entry. Only use audio you are licensed to distribute.
              </div>
              <div className="flex gap-2">
                <Button onClick={() => saveScenes()} disabled={!dirty || busy === 'save'}>Save timing edits</Button>
                <Button variant="primary" onClick={rerender} disabled={running}>Re-render with these settings</Button>
              </div>
            </Panel>
          </div>
        </div>
      )}

      {tab === 'voice' && (
        <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          <Panel className="space-y-4 p-5">
            <SectionTitle title="Voice studio" subtitle="Local narration only. Every render records which engine actually spoke." />
            <Field label="Narration voice" hint="Kokoro MLX appears when its runtime and weights are installed; otherwise macOS say is used fully offline.">
              <select
                className="select"
                value={p.voice}
                onChange={(e) => patchProject({ voice: e.target.value }, 'Voice updated — re-render to regenerate narration with the new voice.')}
              >
                <optgroup label="macOS · offline">
                  {voices.filter((v) => v.engine === 'macos-say').map((v) => (
                    <option key={v.id} value={v.id}>{v.name} ({v.lang})</option>
                  ))}
                </optgroup>
                <optgroup label="Kokoro MLX">
                  {voices.filter((v) => v.engine === 'kokoro-mlx').map((v) => (
                    <option key={v.id} value={v.id} disabled={!v.available}>{v.name}{v.available ? '' : ' — not installed'}</option>
                  ))}
                </optgroup>
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={`Speech rate offset: ${p.voice_speed > 0 ? '+' : ''}${p.voice_speed}`} hint="macOS voices accept -60…+80.">
                <input
                  type="range"
                  min={-60}
                  max={80}
                  step={5}
                  value={p.voice_speed}
                  onChange={(e) => setData((d) => (d ? { ...d, project: { ...d.project, voice_speed: Number(e.target.value) } } : d))}
                  onMouseUp={(e) => patchProject({ voice_speed: Number((e.target as HTMLInputElement).value) }, 'Speech rate updated — re-render to apply.')}
                  className="w-full"
                />
              </Field>
              <Field label="Language">
                <input className="input" value={p.language} onChange={(e) => setData((d) => (d ? { ...d, project: { ...d.project, language: e.target.value } } : d))} onBlur={() => patchProject({ language: p.language })} />
              </Field>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary" onClick={() => previewVoice(p.voice, scenes[0]?.narration)} disabled={!!previewing}>
                {previewing ? <Spinner /> : null} Preview selected voice
              </Button>
              <Button onClick={() => previewVoice(p.voice, 'Here is how your narration will sound in the finished video.')}>
                Preview sample line
              </Button>
            </div>
            {previewUrl && (
              <audio ref={audioRef} controls src={previewUrl} className="w-full" />
            )}
            {sceneTts?.tts_fallback && (
              <Alert tone="amber">
                The last render used a fallback: {sceneTts.tts_fallback} was requested but unavailable ({sceneTts.tts_fallback_reason || 'runtime missing'}).
                The video was narrated with macOS say and this fallback is recorded in project metadata — nothing was silently substituted.
              </Alert>
            )}
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 text-[11px] leading-relaxed text-slate-500">
              Narration is synthesized per scene, then concatenated. On 8 GB memory only one TTS model is resident at a time and scenes are processed sequentially.
            </div>
          </Panel>

          <Panel className="space-y-3 p-5">
            <h3 className="text-sm font-semibold text-slate-200">Scene narration</h3>
            {scenes.length === 0 && <div className="text-sm text-slate-500">No scenes yet.</div>}
            <div className="max-h-[520px] space-y-2 overflow-auto pr-1">
              {scenes.map((sc, i) => {
                const src = sceneAudioUrl(pid, sc);
                return (
                  <div key={i} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-xs font-medium text-slate-200">{i + 1}. {sc.title || 'Scene'}</div>
                        <div className="text-[10px] text-slate-500">{sceneDur(sc).toFixed(1)} s · {sc.tts_engine || 'not generated'}</div>
                      </div>
                      <button
                        onClick={() => previewVoice(p.voice, sc.narration)}
                        className="shrink-0 rounded-lg border border-white/10 px-2 py-1 text-[10px] text-slate-300 hover:bg-white/[0.06]"
                        title="Preview this narration with the selected voice"
                      >
                        Try voice
                      </button>
                    </div>
                    {src && <audio controls preload="none" src={src} className="mt-2 h-8 w-full" />}
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>
      )}

      {tab === 'subtitles' && (
        <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
          <Panel className="space-y-3 p-5">
            <div className="flex items-center justify-between gap-2">
              <SectionTitle title="Subtitle cues" subtitle={`${cues.length} cues · edited cues are preserved (style.customized)`} />
              <div className="flex gap-2">
                <Button variant="subtle" onClick={() => {
                  const last = cues[cues.length - 1];
                  const start = last ? Number(last.end) + 0.2 : 0;
                  setCues([...cues, { start: Number(start.toFixed(2)), end: Number((start + 2.5).toFixed(2)), text: '' }]);
                  setStyle((s) => ({ ...s, customized: true }));
                }}>
                  + Cue
                </Button>
                <Button variant="primary" onClick={saveSubtitles} disabled={busy === 'subs'}>
                  {busy === 'subs' ? <Spinner /> : null} Save cues
                </Button>
              </div>
            </div>
            <div className="max-h-[560px] space-y-2 overflow-auto pr-1">
              {cues.length === 0 && (
                <div className="rounded-xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-slate-500">
                  No subtitle cues yet. Run a render or generate subtitles from narration timings first.
                </div>
              )}
              {cues.map((c, i) => (
                <div key={i} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5">
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      step={0.1}
                      className="input w-20 px-2 py-1 text-[11px]"
                      value={Number(c.start).toFixed(2)}
                      onChange={(e) => setCues((prev) => prev.map((x, idx) => (idx === i ? { ...x, start: Number(e.target.value) } : x)))}
                    />
                    <span className="text-[10px] text-slate-500">→</span>
                    <input
                      type="number"
                      step={0.1}
                      className="input w-20 px-2 py-1 text-[11px]"
                      value={Number(c.end).toFixed(2)}
                      onChange={(e) => setCues((prev) => prev.map((x, idx) => (idx === i ? { ...x, end: Number(e.target.value) } : x)))}
                    />
                    <span className="text-[10px] text-slate-600">{c.scene ? `scene ${c.scene}` : ''}</span>
                    <button
                      onClick={() => setCues((prev) => prev.filter((_, idx) => idx !== i))}
                      className="ml-auto rounded px-1.5 py-0.5 text-[11px] text-slate-500 hover:bg-rose-500/10 hover:text-rose-300"
                    >
                      remove
                    </button>
                  </div>
                  <input
                    className="input mt-2 py-1.5 text-[12px]"
                    value={c.text}
                    onChange={(e) => setCues((prev) => prev.map((x, idx) => (idx === i ? { ...x, text: e.target.value } : x)))}
                    placeholder="Cue text"
                  />
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="space-y-4 p-5">
            <SectionTitle title="Caption style" subtitle="Applied to ASS burn-in; SRT/VTT stay plain text." />
            <label className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2.5">
              <span className="text-sm text-slate-300">Subtitles enabled</span>
              <input
                type="checkbox"
                checked={!!p.subtitle_enabled}
                onChange={(e) => patchProject({ subtitle_enabled: e.target.checked }, 'Subtitle generation updated.')}
                className="h-4 w-4 accent-indigo-500"
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Position">
                <select className="select" value={style.position || 'bottom'} onChange={(e) => setStyle({ ...style, position: e.target.value, customized: true })}>
                  <option value="bottom">Bottom</option>
                  <option value="center">Center</option>
                  <option value="top">Top</option>
                </select>
              </Field>
              <Field label="Font size">
                <input type="number" min={20} max={96} className="input" value={style.size || 46} onChange={(e) => setStyle({ ...style, size: Number(e.target.value), customized: true })} />
              </Field>
              <Field label="Text color">
                <input type="color" className="input h-10 p-1" value={style.primary || '#FFFFFF'} onChange={(e) => setStyle({ ...style, primary: e.target.value, customized: true })} />
              </Field>
              <Field label="Keyword highlight">
                <input type="color" className="input h-10 p-1" value={style.highlight || '#FFD166'} onChange={(e) => setStyle({ ...style, highlight: e.target.value, customized: true })} />
              </Field>
              <Field label="Outline">
                <input type="color" className="input h-10 p-1" value={style.outline || '#000000'} onChange={(e) => setStyle({ ...style, outline: e.target.value, customized: true })} />
              </Field>
              <Field label="Max chars / cue">
                <input type="number" min={16} max={90} className="input" value={style.max_chars || 42} onChange={(e) => setStyle({ ...style, max_chars: Number(e.target.value), customized: true })} />
              </Field>
            </div>
            <label className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2.5">
              <span className="text-sm text-slate-300">Bold captions</span>
              <input type="checkbox" checked={style.bold !== false} onChange={(e) => setStyle({ ...style, bold: e.target.checked, customized: true })} className="h-4 w-4 accent-indigo-500" />
            </label>
            <label className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2.5">
              <span className="text-sm text-slate-300">Highlight keywords automatically</span>
              <input type="checkbox" checked={style.keyword_highlight !== false} onChange={(e) => setStyle({ ...style, keyword_highlight: e.target.checked, customized: true })} className="h-4 w-4 accent-indigo-500" />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={saveSubtitles} disabled={busy === 'subs'}>Save style & rebuild</Button>
              <Button onClick={startPreview}>Save without closing</Button>
              <a href={api.fileUrl(pid, 'srt')} className="inline-flex items-center rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 hover:bg-white/[0.06]">SRT</a>
              <a href={api.fileUrl(pid, 'vtt')} className="inline-flex items-center rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 hover:bg-white/[0.06]">VTT</a>
              <a href={api.fileUrl(pid, 'ass')} className="inline-flex items-center rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 hover:bg-white/[0.06]">ASS</a>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[11px] leading-relaxed text-slate-500">
              Caption timings come from real narration audio. Whisper.cpp forced alignment is optional when its binary and model are installed; this build uses narration timing segmentation by default.
            </div>
          </Panel>
        </div>
      )}

      {tab === 'assets' && (
        <div className="space-y-4">
          <Panel className="flex flex-wrap items-center justify-between gap-3 p-4">
            <p className="text-xs text-slate-400">Project media is stored on disk under <span className="font-mono text-slate-300">data/projects/{pid.slice(0, 8)}…</span> and survives restarts.</p>
            <div className="flex gap-2">
              <label className="cursor-pointer rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-white/[0.06]">
                Upload image
                <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={async (e) => {
                  const f = e.target.files?.[0];
                  e.target.value = '';
                  if (!f) return;
                  try {
                    await api.uploadAsset(pid, 'images', f);
                    setAssets(await api.projectAssets(pid));
                    setNotice('Image added to project assets.');
                  } catch (er: any) { setErr(String(er.message || er)); }
                }} />
              </label>
              <label className="cursor-pointer rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-white/[0.06]">
                Upload music
                <input type="file" accept="audio/*" className="hidden" onChange={async (e) => {
                  const f = e.target.files?.[0];
                  e.target.value = '';
                  if (!f) return;
                  try {
                    await api.uploadAsset(pid, 'music', f);
                    setAssets(await api.projectAssets(pid));
                    setNotice('Music added to this project.');
                  } catch (er: any) { setErr(String(er.message || er)); }
                }} />
              </label>
              <label className="cursor-pointer rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-white/[0.06]">
                Upload SFX
                <input type="file" accept="audio/*" className="hidden" onChange={async (e) => {
                  const f = e.target.files?.[0];
                  e.target.value = '';
                  if (!f) return;
                  try {
                    await api.uploadAsset(pid, 'sfx', f);
                    setAssets(await api.projectAssets(pid));
                    setNotice('SFX added to this project.');
                  } catch (er: any) { setErr(String(er.message || er)); }
                }} />
              </label>
            </div>
          </Panel>

          <AssetSection title="Images" items={assets?.images || []} pid={pid} preview />
          <AssetSection title="Audio" items={assets?.audio || []} pid={pid} />
          <AssetSection title="Video, subtitles & renders" items={assets?.other || []} pid={pid} />
        </div>
      )}

      {tab === 'export' && (
        <div className="space-y-4">
          {result?.final_video ? (
            <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
              <Panel className="overflow-hidden p-0">
                <video
                  key={`${result.final_video}-${result.completed_at || cache}`}
                  controls
                  className="aspect-video w-full bg-black"
                  src={`${api.fileUrl(pid, 'video')}?v=${encodeURIComponent(String(result.completed_at || cache))}`}
                />
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.06] px-4 py-3">
                  <div className="text-xs text-slate-400">
                    {result.resolution || '720p'} · {result.fps || p.fps} fps · {fmtDuration(result.duration_sec)} · {fmtBytes(result.size_bytes)}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <a href={api.fileUrl(pid, 'video')} download className="inline-flex items-center rounded-xl bg-gradient-to-b from-indigo-500 to-indigo-600 px-3.5 py-2 text-sm font-medium text-white shadow-lg shadow-indigo-950/40">Download MP4</a>
                    <a href={api.fileUrl(pid, 'srt')} download className="inline-flex items-center rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-white/[0.06]">SRT</a>
                    <a href={api.fileUrl(pid, 'vtt')} download className="inline-flex items-center rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-white/[0.06]">VTT</a>
                    <a href={api.fileUrl(pid, 'ass')} download className="inline-flex items-center rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-white/[0.06]">ASS</a>
                    <a href={api.fileUrl(pid, 'result')} target="_blank" rel="noreferrer" className="inline-flex items-center rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-200 hover:bg-white/[0.06]">Result JSON</a>
                  </div>
                </div>
              </Panel>

              <div className="space-y-4">
                <Panel className="space-y-3 p-5">
                  <SectionTitle title="Render report" subtitle="Measured from the produced file and the job that made it." />
                  <Metric label="Duration" value={fmtDuration(result.duration_sec)} />
                  <Metric label="Resolution" value={result.resolution || '—'} />
                  <Metric label="Frame rate" value={`${result.fps || p.fps} fps`} />
                  <Metric label="Size" value={fmtBytes(result.size_bytes)} />
                  <Metric label="Bitrate" value={result.bitrate_kbps ? `${result.bitrate_kbps} kb/s` : '—'} />
                  <Metric label="Peak memory" value={result.peak_memory_mb ? `${result.peak_memory_mb} MB` : '—'} />
                  <Metric label="Render time" value={result.render_seconds ? `${result.render_seconds} s` : '—'} />
                  <Metric label="Subtitle cues" value={String(result.subtitle_cues ?? cues.length)} />
                  <Metric label="Burned captions" value={result.subtitles_burned ? 'yes' : 'no'} />
                  <Metric label="Visual mode" value="animated graphics" />
                </Panel>

                <Panel className="space-y-3 p-5">
                  <h3 className="text-sm font-semibold text-slate-200">Apply changes</h3>
                  <p className="text-[11px] leading-relaxed text-slate-500">
                    Re-render rebuilds segments from the current storyboard, re-synthesizes narration only where the text changed, and remuxes the final MP4.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="primary" onClick={rerender} disabled={running || !scenes.length}>Re-render video</Button>
                    <Button onClick={() => runJob(() => api.generate(pid), 'Full pipeline')} disabled={running}>Rebuild from scratch</Button>
                  </div>
                  <a href={api.fileUrl(pid, 'log')} target="_blank" rel="noreferrer" className="inline-block text-[11px] text-indigo-300 hover:text-indigo-200">Open pipeline log →</a>
                </Panel>
              </div>
            </div>
          ) : (
            <Empty
              title="No final render yet"
              hint={running ? 'A render is in progress — the preview appears when composition finishes.' : 'Run the full pipeline to produce a 720p H.264/AAC MP4.'}
              action={<Button variant="primary" onClick={fullRender} disabled={running}>{running ? 'Rendering…' : 'Generate full video'}</Button>}
            />
          )}

          <Panel className="space-y-3 p-5">
            <SectionTitle title="Render history" subtitle="Every successful render keeps an entry and the previous files remain on disk." />
            {(data.history || []).length === 0 ? (
              <div className="text-sm text-slate-500">No renders recorded yet.</div>
            ) : (
              <div className="overflow-hidden rounded-xl border border-white/[0.06]">
                <table className="w-full text-left text-xs">
                  <thead className="bg-white/[0.03] text-slate-500">
                    <tr>
                      <th className="px-3 py-2 font-medium">Completed</th>
                      <th className="px-3 py-2 font-medium">Duration</th>
                      <th className="px-3 py-2 font-medium">Size</th>
                      <th className="px-3 py-2 font-medium">Peak RAM</th>
                      <th className="px-3 py-2 font-medium">FPS</th>
                      <th className="px-3 py-2 font-medium">File</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...(data.history || [])].reverse().map((h, i) => (
                      <tr key={i} className="border-t border-white/[0.05] text-slate-300">
                        <td className="px-3 py-2">{h.at ? new Date(h.at).toLocaleString() : '—'}</td>
                        <td className="px-3 py-2">{fmtDuration(h.duration_sec)}</td>
                        <td className="px-3 py-2">{fmtBytes(h.size_bytes)}</td>
                        <td className="px-3 py-2">{h.peak_memory_mb ? `${h.peak_memory_mb} MB` : '—'}</td>
                        <td className="px-3 py-2">{h.fps || '—'}</td>
                        <td className="px-3 py-2 font-mono text-[10px] text-slate-500">{(h.video || '').split('/').pop()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel className="space-y-2 p-5">
            <h3 className="text-sm font-semibold text-slate-200">Job history</h3>
            {jobs.length === 0 && <div className="text-sm text-slate-500">No jobs yet.</div>}
            <div className="space-y-1.5">
              {jobs.slice(0, 8).map((j) => (
                <div key={j.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-white/[0.05] bg-white/[0.02] px-3 py-1.5 text-[11px]">
                  <Badge tone={statusTone(j.status)}>{j.status}</Badge>
                  <span className="text-slate-300">{j.type}</span>
                  <span className="text-slate-500">{j.stage}</span>
                  <span className="ml-auto text-slate-500">{j.created_at ? new Date(j.created_at).toLocaleString() : ''}</span>
                  {j.peak_memory_mb ? <span className="text-slate-500">{j.peak_memory_mb} MB peak</span> : null}
                </div>
              ))}
            </div>
          </Panel>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.06] pt-4 text-[11px] text-slate-600">
        <span>
          Job engine: sequential · output: {p.aspect_ratio === '9:16' ? '720×1280' : p.aspect_ratio === '1:1' ? '720×720' : '1280×720'} H.264 / AAC
        </span>
        <span>{jobMeta?.engine_note || 'Runs entirely on this Mac. No cloud inference.'}</span>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-white/[0.04] pb-1.5 text-xs last:border-0 last:pb-0">
      <span className="text-slate-500">{label}</span>
      <span className="font-medium text-slate-200">{value}</span>
    </div>
  );
}

function AssetSection({ title, items, pid, preview = false }: { title: string; items: any[]; pid: string; preview?: boolean }) {
  return (
    <Panel className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
        <span className="text-[11px] text-slate-500">{items.length} files</span>
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-slate-500">Nothing here yet.</div>
      ) : preview ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((a) => (
            <a key={a.rel} href={a.url} target="_blank" rel="noreferrer" className="group overflow-hidden rounded-xl border border-white/[0.06] bg-slate-950/50">
              <img src={a.url} alt={a.name} className="aspect-video w-full object-cover opacity-85 transition group-hover:opacity-100" />
              <div className="truncate px-2 py-1.5 text-[10px] text-slate-400">{a.name}</div>
            </a>
          ))}
        </div>
      ) : (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {items.map((a) => (
            <a key={a.rel} href={a.url} target="_blank" rel="noreferrer" className="flex items-center justify-between gap-2 rounded-lg border border-white/[0.05] bg-white/[0.02] px-2.5 py-1.5 text-[11px] text-slate-300 hover:bg-white/[0.05]">
              <span className="truncate">{a.rel}</span>
              <span className="shrink-0 text-slate-500">{fmtBytes(a.size)}</span>
            </a>
          ))}
        </div>
      )}
    </Panel>
  );
}
