import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  clipApi,
  ClipCandidateT,
  ClipJobT,
  ClipProjectDetailT,
  fmtBytes,
  fmtDuration,
} from '../lib/api';
import { Alert, Badge, Button, Empty, Field, Panel, Progress, SectionTitle, Spinner, statusTone } from '../components/ui';

const DURATIONS = [15, 30, 45, 60, 90];
const ASPECTS = ['9:16', '16:9', '1:1'];
const CROP_MODES = [
  { id: 'center', label: 'Center' },
  { id: 'left', label: 'Left' },
  { id: 'right', label: 'Right' },
  { id: 'top', label: 'Top' },
  { id: 'bottom', label: 'Bottom' },
  { id: 'custom', label: 'Manual rect' },
];
const POSITIONS = ['bottom', 'center', 'top'];

type Seg = { start: number; end: number; text: string };

function ts(sec: number): string {
  const s = Math.max(0, Number(sec || 0));
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${m}:${r.toFixed(1).padStart(4, '0')}`;
}

function ScoreBars({ clip }: { clip: ClipCandidateT }) {
  const comps = clip.score_json?.components || {};
  const rows = Object.entries(comps);
  if (!rows.length) return null;
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
      {rows.map(([name, c]) => (
        <div key={name} className="text-[11px]">
          <div className="flex items-center justify-between text-slate-400">
            <span className="capitalize">{name}</span>
            <span className="tabular-nums text-slate-300">
              {c.raw.toFixed(2)} × {c.weight.toFixed(2)}
            </span>
          </div>
          <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-white/[0.06]">
            <div className="h-full rounded-full bg-indigo-400/70" style={{ width: `${Math.round(c.raw * 100)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function ClipProject() {
  const { id } = useParams();
  const pid = id || '';
  const [data, setData] = useState<ClipProjectDetailT | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<ClipJobT | null>(null);

  // transcript editor
  const [segs, setSegs] = useState<Seg[]>([]);
  const [importText, setImportText] = useState('');
  const [importName, setImportName] = useState('');
  const [dirty, setDirty] = useState(false);

  // highlight controls
  const [durations, setDurations] = useState<number[]>([30]);
  const [customDur, setCustomDur] = useState('');
  const [count, setCount] = useState(5);

  // per-clip editor buffers
  const [editing, setEditing] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, any>>({});
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);

  const reload = useCallback(async () => {
    try {
      const d = await clipApi.project(pid);
      setData(d);
      setErr('');
      const t = d.transcript;
      const source: Seg[] = (t?.segments?.length ? t.segments : t?.sentences || []).map((s: any) => ({
        start: Number(s.start || 0),
        end: Number(s.end || 0),
        text: String(s.text || ''),
      }));
      setSegs(source);
      setDirty(false);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [pid]);

  useEffect(() => {
    reload();
  }, [reload]);

  // poll the active Engine B job
  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    const tick = async () => {
      try {
        const r = await clipApi.job(jobId);
        if (!alive) return;
        setJob(r.job);
        if (['succeeded', 'failed', 'canceled', 'interrupted'].includes(r.job.status)) {
          setBusy('');
          setJobId(null);
          if (r.job.status === 'failed') setErr(r.job.error || r.job.message || 'Job failed');
          await reload();
        }
      } catch (e: any) {
        if (alive) setErr(String(e.message || e));
      }
    };
    tick();
    const t = setInterval(tick, 1000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [jobId, reload]);

  const run = async (label: string, fn: () => Promise<{ job: ClipJobT }>) => {
    setBusy(label);
    setErr('');
    setNotice('');
    try {
      const r = await fn();
      setJob(r.job);
      setJobId(r.job.id);
    } catch (e: any) {
      setBusy('');
      setErr(String(e.message || e));
    }
  };

  const upload = async (file: File) => {
    setUploading(true);
    setErr('');
    try {
      const r: any = await clipApi.uploadSource(pid, file, true);
      const rep = r.replaced || {};
      setNotice(
        rep.sources || rep.clips
          ? `Source replaced. Cleared ${rep.sources} previous source(s) and ${rep.clips} clip candidate(s).`
          : 'Source uploaded and probed.',
      );
      await reload();
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setUploading(false);
    }
  };

  const importFile = async (file: File) => {
    setUploading(true);
    setErr('');
    try {
      const text = await file.text();
      const r = await clipApi.importTranscript(pid, text, file.name);
      setImportName(file.name);
      setImportText('');
      setNotice(`Imported ${r.transcript.segments.length} cue(s) from ${file.name}.`);
      await reload();
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setUploading(false);
    }
  };

  const saveTranscript = async () => {
    setBusy('Saving transcript');
    try {
      await clipApi.saveTranscript(pid, segs);
      setNotice('Transcript saved. Re-run highlights to refresh clip candidates.');
      await reload();
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy('');
    }
  };

  const project = data?.project;
  const caps = data?.capabilities;
  const clips = data?.clips || [];
  const selected = clips.filter((c) => c.selected);

  const draft = (c: ClipCandidateT) =>
    drafts[c.id] || {
      aspect: c.edit?.aspect || project?.aspect_ratio || '9:16',
      preset: c.edit?.preset || project?.preset || 'tiktok',
      crop: c.edit?.crop || { mode: 'center' },
      burn_captions: c.edit?.burn_captions !== false,
      fps: c.edit?.fps || 30,
      caption_style: c.edit?.caption_style || { size: 54, position: 'bottom', max_chars: 32, highlight: '#FFD166' },
      audio: c.edit?.audio || { normalize: true, music: null, music_volume: 0.18 },
      start_sec: c.start_sec,
      end_sec: c.end_sec,
    };

  const setDraft = (cid: string, patch: any) =>
    setDrafts((d) => ({ ...d, [cid]: { ...(d[cid] || draft(clips.find((c) => c.id === cid)!)), ...patch } }));

  const toggleDuration = (d: number) =>
    setDurations((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d].slice(0, 6)));

  const addCustom = () => {
    const v = Math.round(Number(customDur));
    if (!v || v < 5 || v > 180) {
      setErr('Custom duration must be between 5 and 180 seconds.');
      return;
    }
    setDurations((cur) => (cur.includes(v) ? cur : [...cur, v].slice(0, 6)));
    setCustomDur('');
  };

  const header = useMemo(() => {
    if (!project) return null;
    return (
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <Link to="/clip" className="hover:text-slate-300">
              Auto-Clip
            </Link>
            <span>/</span>
            <span className="truncate">{project.id.slice(0, 8)}</span>
          </div>
          <h1 className="mt-1 truncate text-lg font-semibold text-white">{project.title}</h1>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[11px]">
            <Badge tone={statusTone(project.status)}>{project.status}</Badge>
            <Badge tone="slate">{project.aspect_ratio}</Badge>
            <Badge tone="slate">{project.preset}</Badge>
            <Badge tone="slate">{project.language}</Badge>
            {project.source && (
              <Badge tone="slate">
                {project.source.width}×{project.source.height} · {fmtDuration(project.source.duration_sec)}
              </Badge>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {data?.analysis && (
            <span className="text-[11px] text-slate-500">
              {data.analysis.silence_gaps} pauses · {data.analysis.scene_cuts} scene cuts
            </span>
          )}
          <Button variant="subtle" onClick={reload} disabled={!!busy}>
            Reload
          </Button>
        </div>
      </div>
    );
  }, [project, data, busy, reload]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-16 text-[13px] text-slate-400">
        <Spinner /> Loading clip project…
      </div>
    );
  }
  if (!project) {
    return <Alert>{err || 'Clip project not found.'}</Alert>;
  }

  const jobRunning = !!jobId || !!busy;

  return (
    <div className="space-y-5">
      {header}
      {err && <Alert>{err}</Alert>}
      {notice && <Alert tone="green">{notice}</Alert>}

      {job && (
        <Panel>
          <div className="flex flex-wrap items-center justify-between gap-2 text-[12px]">
            <div className="flex items-center gap-2">
              <Badge tone={statusTone(job.status)}>{job.status}</Badge>
              <span className="text-slate-300">{job.type}</span>
              <span className="text-slate-500">· {job.stage}</span>
              <span className="text-slate-400">{job.message}</span>
            </div>
            <div className="flex items-center gap-3 text-[11px] text-slate-500">
              {job.peak_memory_mb ? <span>peak {job.peak_memory_mb} MB</span> : null}
              {['queued', 'running'].includes(job.status) && (
                <Button variant="danger" onClick={() => clipApi.cancelJob(job.id)}>
                  Cancel
                </Button>
              )}
            </div>
          </div>
          <div className="mt-2">
            <Progress value={job.progress} />
          </div>
          {job.error && <div className="mt-2 whitespace-pre-wrap text-[11px] text-rose-300">{job.error}</div>}
        </Panel>
      )}

      {/* 1. source */}
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-[15px] font-semibold text-white">1 · Source recording</h2>
            <p className="mt-0.5 text-[12px] text-slate-400">
              One source per project. Uploading again replaces the current video and clears its transcript, highlights
              and clips.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept="video/mp4,video/quicktime,video/x-matroska,video/webm,.mp4,.mov,.mkv,.webm"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload(f);
                e.currentTarget.value = '';
              }}
            />
            <Button variant="primary" onClick={() => fileRef.current?.click()} disabled={uploading || jobRunning}>
              {uploading ? <Spinner /> : null}
              {project.source ? 'Replace video' : 'Upload video'}
            </Button>
          </div>
        </div>

        {project.source ? (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <video
              key={project.source.url}
              src={clipApi.sourceUrl(pid)}
              controls
              preload="metadata"
              className="w-full rounded-xl border border-white/10 bg-black"
            />
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 self-start text-[12px]">
              {[
                ['File', project.source.original_name],
                ['Container', project.source.ext],
                ['Duration', fmtDuration(project.source.duration_sec)],
                ['Frame', `${project.source.width}×${project.source.height} @ ${project.source.fps || '—'} fps`],
                ['Video', project.source.vcodec || '—'],
                ['Audio', `${project.source.acodec || '—'} · ${project.source.channels || '?'} ch · ${project.source.sample_rate || '?'} Hz`],
                ['Size', fmtBytes(project.source.size_bytes)],
                ['Probe', project.source.probe?.probe_source || 'unknown'],
              ].map(([k, v]) => (
                <div key={k as string}>
                  <div className="text-[10px] uppercase tracking-wide text-slate-500">{k}</div>
                  <div className="truncate text-slate-200">{v as string}</div>
                </div>
              ))}
              <div className="col-span-2">
                <div className="text-[10px] uppercase tracking-wide text-slate-500">SHA-256 (uploaded bytes)</div>
                <div className="break-all font-mono text-[10px] text-slate-400">{project.source.sha256}</div>
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-4">
            <Empty title="No source yet" hint="Upload an MP4, MOV, MKV or WebM file with an audio track." />
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            disabled={!project.source || jobRunning}
            onClick={() => run('Analyzing', () => clipApi.analyze(pid))}
          >
            Run analysis
          </Button>
          <span className="text-[11px] text-slate-500">
            Audio extraction, loudness envelope, silence gaps and scene cuts (approximate, 2 fps scan).
          </span>
        </div>
      </Panel>

      {/* 2. transcript */}
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-[15px] font-semibold text-white">2 · Transcript</h2>
            <p className="mt-0.5 text-[12px] text-slate-400">
              {data?.transcript
                ? `Backend: ${data.transcript.backend} · timing ${data.transcript.timing} · word timing ${
                    data.transcript.word_timing || 'n/a'
                  }`
                : 'No transcript yet. Speech recognition is optional — you can import subtitles you already have.'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              disabled={!caps?.available || !project.source || jobRunning}
              title={caps?.available ? 'Run local whisper.cpp' : 'Local ASR backend not installed'}
              onClick={() => run('Transcribing', () => clipApi.transcribe(pid))}
            >
              Transcribe locally
            </Button>
          </div>
        </div>

        {!caps?.available && (
          <div className="mt-3">
            <Alert tone="amber">
              Local ASR is unavailable: {caps?.reasons?.join(' · ') || 'no backend detected'}. Import an SRT/VTT below,
              or install whisper.cpp with{' '}
              <code className="rounded bg-black/30 px-1">scripts/install_whisper_cpp.sh</code>. Nothing is fabricated.
            </Alert>
          </div>
        )}

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
            <div className="text-[12px] font-medium text-slate-200">Import SRT / VTT</div>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Cue timings are taken from your file; word timings inside a cue are estimated and labelled as such.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input
                type="file"
                accept=".srt,.vtt,text/plain"
                className="text-[11px] text-slate-400 file:mr-2 file:rounded-lg file:border file:border-white/10 file:bg-white/[0.06] file:px-2.5 file:py-1.5 file:text-[11px] file:text-slate-200"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) importFile(f);
                  e.currentTarget.value = '';
                }}
              />
              {importName && <span className="text-[11px] text-slate-500">last: {importName}</span>}
            </div>
          </div>

          <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
            <div className="text-[12px] font-medium text-slate-200">Paste transcript</div>
            <p className="mt-0.5 text-[11px] text-slate-500">
              SRT, WebVTT or plain text. Plain text gives text-only copy — timed clips need timings.
            </p>
            <textarea
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              placeholder={'1\n00:00:01,000 --> 00:00:04,500\nText of the cue…'}
              className="mt-2 h-24 w-full resize-y rounded-lg border border-white/10 bg-slate-950/60 p-2 font-mono text-[11px] text-slate-200 outline-none focus:border-indigo-400/50"
            />
            <div className="mt-2">
              <Button
                variant="ghost"
                disabled={!importText.trim() || uploading}
                onClick={async () => {
                  setUploading(true);
                  setErr('');
                  try {
                    const r = await clipApi.importTranscript(pid, importText, 'pasted.srt');
                    setImportText('');
                    setNotice(`Imported ${r.transcript.segments.length} cue(s).`);
                    await reload();
                  } catch (e: any) {
                    setErr(String(e.message || e));
                  } finally {
                    setUploading(false);
                  }
                }}
              >
                Import pasted transcript
              </Button>
            </div>
          </div>
        </div>

        {segs.length > 0 && (
          <div className="mt-4">
            <div className="flex items-center justify-between">
              <div className="text-[12px] font-medium text-slate-200">Cues ({segs.length})</div>
              <div className="flex items-center gap-2">
                {dirty && <span className="text-[11px] text-amber-300">unsaved edits</span>}
                <Button variant="ghost" disabled={!dirty || jobRunning} onClick={saveTranscript}>
                  Save transcript
                </Button>
              </div>
            </div>
            <div className="mt-2 max-h-72 space-y-1.5 overflow-y-auto pr-1">
              {segs.map((s, i) => (
                <div key={i} className="flex items-start gap-2 rounded-lg border border-white/[0.05] bg-white/[0.02] p-2">
                  <div className="flex w-24 shrink-0 flex-col gap-1">
                    <input
                      type="number"
                      step="0.01"
                      value={s.start}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        setSegs((cur) => cur.map((x, j) => (j === i ? { ...x, start: v } : x)));
                        setDirty(true);
                      }}
                      className="w-full rounded border border-white/10 bg-slate-950/70 px-1.5 py-1 text-[10px] tabular-nums text-slate-200"
                    />
                    <input
                      type="number"
                      step="0.01"
                      value={s.end}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        setSegs((cur) => cur.map((x, j) => (j === i ? { ...x, end: v } : x)));
                        setDirty(true);
                      }}
                      className="w-full rounded border border-white/10 bg-slate-950/70 px-1.5 py-1 text-[10px] tabular-nums text-slate-200"
                    />
                  </div>
                  <textarea
                    value={s.text}
                    onChange={(e) => {
                      const v = e.target.value;
                      setSegs((cur) => cur.map((x, j) => (j === i ? { ...x, text: v } : x)));
                      setDirty(true);
                    }}
                    rows={2}
                    className="min-h-[46px] w-full resize-y rounded border border-white/10 bg-slate-950/60 p-1.5 text-[11px] text-slate-200 outline-none focus:border-indigo-400/40"
                  />
                </div>
              ))}
            </div>
          </div>
        )}
      </Panel>

      {/* 3. highlights */}
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-[15px] font-semibold text-white">3 · Highlight detection</h2>
            <p className="mt-0.5 text-[12px] text-slate-400">
              Deterministic scoring over transcript sentences + audio structure. Every component and weight is shown on
              each clip, so you can audit the ranking. This is not a virality prediction.
            </p>
          </div>
          <Button
            variant="primary"
            disabled={!data?.transcript || durations.length === 0 || jobRunning}
            onClick={() => run('Scoring highlights', () => clipApi.highlights(pid, durations, count))}
          >
            Generate clips
          </Button>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Target durations (seconds)</div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              {DURATIONS.map((d) => (
                <button
                  key={d}
                  onClick={() => toggleDuration(d)}
                  className={`rounded-lg border px-2.5 py-1.5 text-[12px] transition ${
                    durations.includes(d)
                      ? 'border-indigo-400/40 bg-indigo-500/15 text-white'
                      : 'border-white/10 bg-white/[0.02] text-slate-300 hover:border-white/20'
                  }`}
                >
                  {d}s
                </button>
              ))}
              <div className="flex items-center gap-1">
                <input
                  value={customDur}
                  onChange={(e) => setCustomDur(e.target.value)}
                  placeholder="custom"
                  className="w-20 rounded-lg border border-white/10 bg-slate-950/60 px-2 py-1.5 text-[12px] text-slate-200 outline-none"
                />
                <Button variant="subtle" onClick={addCustom}>
                  Add
                </Button>
              </div>
            </div>
            <div className="mt-1 text-[11px] text-slate-500">
              Selected: {durations.length ? durations.sort((a, b) => a - b).map((d) => `${d}s`).join(', ') : 'none'} ·
              windows stay sentence-aligned between 80–130% of each target and never overlap.
            </div>
          </div>
          <Field label="Clips to return" hint="Non-overlapping; a shortfall is reported honestly">
            <input
              type="number"
              min={1}
              max={12}
              value={count}
              onChange={(e) => setCount(Math.max(1, Math.min(12, Number(e.target.value) || 1)))}
              className="w-full rounded-xl border border-white/10 bg-slate-950/60 px-3 py-2 text-[13px] text-slate-100"
            />
          </Field>
        </div>
      </Panel>

      {/* 4. clips */}
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-[15px] font-semibold text-white">4 · Clips ({clips.length})</h2>
            <p className="mt-0.5 text-[12px] text-slate-400">
              Edit boundaries, crop and captions per clip, then render 720p H.264/AAC.
            </p>
          </div>
          <Button
            variant="primary"
            disabled={!selected.length || jobRunning}
            onClick={() => run('Exporting batch', () => clipApi.exportBatch(pid, selected.map((c) => c.id), project.aspect_ratio))}
          >
            Export {selected.length} selected
          </Button>
        </div>

        {clips.length === 0 ? (
          <div className="mt-4">
            <Empty
              title="No clips yet"
              hint="Import or transcribe audio, then generate clips from the panel above."
            />
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {clips.map((c) => {
              const d = draft(c);
              const open = editing === c.id;
              const rendered = c.renders[c.renders.length - 1];
              return (
                <div key={c.id} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={c.selected}
                          onChange={async (e) => {
                            await clipApi.patchClip(c.id, { selected: e.target.checked });
                            reload();
                          }}
                          className="h-3.5 w-3.5 accent-indigo-500"
                        />
                        <div className="truncate text-[13px] font-semibold text-slate-100">
                          {c.title || c.transcript_text.slice(0, 60) || 'Untitled clip'}
                        </div>
                        <Badge tone="slate">{c.category}</Badge>
                        <Badge tone={statusTone(c.state)}>{c.state}</Badge>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                        <span className="tabular-nums text-slate-300">
                          {ts(c.start_sec)} → {ts(c.end_sec)}
                        </span>
                        <span>· {c.duration_sec.toFixed(1)}s</span>
                        <span>· score {c.score.toFixed(0)}/100</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button variant="subtle" onClick={() => setEditing(open ? null : c.id)}>
                        {open ? 'Close editor' : 'Edit & render'}
                      </Button>
                      <Button variant="danger" onClick={async () => {
                        await clipApi.deleteClip(c.id);
                        reload();
                      }}>
                        Delete
                      </Button>
                    </div>
                  </div>

                  <p className="mt-2 whitespace-pre-wrap text-[12px] leading-relaxed text-slate-300">
                    {c.transcript_text}
                  </p>
                  {c.hook && c.hook !== c.title && (
                    <p className="mt-1 text-[11px] text-indigo-200/80">Hook: {c.hook}</p>
                  )}
                  <p className="mt-1 text-[11px] text-slate-500">{c.reason}</p>

                  <div className="mt-2 grid gap-3 lg:grid-cols-2">
                    <ScoreBars clip={c} />
                    {c.score_json?.metrics && (
                      <div className="flex flex-wrap content-start gap-x-3 gap-y-1 text-[11px] text-slate-500">
                        <span>{c.score_json.metrics.words} words</span>
                        <span>{c.score_json.metrics.words_per_sec} w/s</span>
                        <span>{c.score_json.metrics.mean_dbfs ?? '—'} dBFS</span>
                        <span>{Math.round((c.score_json.metrics.silence_ratio || 0) * 100)}% silence</span>
                      </div>
                    )}
                  </div>

                  {rendered && (
                    <div className="mt-3 grid gap-3 lg:grid-cols-2">
                      <video
                        src={clipApi.clipFileUrl(c.id, rendered.aspect_ratio)}
                        controls
                        preload="metadata"
                        className="w-full rounded-lg border border-white/10 bg-black"
                      />
                      <div className="text-[11px] text-slate-400">
                        <div>
                          Latest render: {rendered.aspect_ratio} · {rendered.aspect_ratio === '9:16' ? '720×1280' : rendered.aspect_ratio === '16:9' ? '1280×720' : '720×720'} ·{' '}
                          {fmtDuration(rendered.duration_sec)} · {fmtBytes(rendered.size_bytes)}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-2">
                          {c.renders.map((r) => (
                            <a
                              key={r.id}
                              href={clipApi.clipFileUrl(c.id, r.aspect_ratio)}
                              download
                              className="rounded-lg border border-white/10 bg-white/[0.04] px-2 py-1 text-[11px] text-slate-200 hover:bg-white/[0.08]"
                            >
                              Download {r.aspect_ratio}
                            </a>
                          ))}
                        </div>
                        <div className="mt-2 space-y-0.5 font-mono text-[10px] text-slate-500">
                          <div>probe: {rendered.probe?.probe_source || '—'}</div>
                          <div>
                            {rendered.probe?.video_codec} / {rendered.probe?.audio_codec} ·{' '}
                            {rendered.probe?.width}×{rendered.probe?.height}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {open && (
                    <div className="mt-3 rounded-xl border border-white/[0.07] bg-slate-950/40 p-3">
                      <div className="grid gap-3 sm:grid-cols-4">
                        <Field label="Start (s)">
                          <input
                            type="number"
                            step="0.1"
                            value={d.start_sec}
                            onChange={(e) => setDraft(c.id, { start_sec: Number(e.target.value) })}
                            className="w-full rounded-lg border border-white/10 bg-slate-950/70 px-2 py-1.5 text-[12px] text-slate-200"
                          />
                        </Field>
                        <Field label="End (s)">
                          <input
                            type="number"
                            step="0.1"
                            value={d.end_sec}
                            onChange={(e) => setDraft(c.id, { end_sec: Number(e.target.value) })}
                            className="w-full rounded-lg border border-white/10 bg-slate-950/70 px-2 py-1.5 text-[12px] text-slate-200"
                          />
                        </Field>
                        <Field label="Aspect">
                          <select
                            value={d.aspect}
                            onChange={(e) => setDraft(c.id, { aspect: e.target.value })}
                            className="w-full rounded-lg border border-white/10 bg-slate-950/70 px-2 py-1.5 text-[12px] text-slate-200"
                          >
                            {ASPECTS.map((a) => (
                              <option key={a} value={a}>
                                {a}
                              </option>
                            ))}
                          </select>
                        </Field>
                        <Field label="FPS">
                          <select
                            value={d.fps}
                            onChange={(e) => setDraft(c.id, { fps: Number(e.target.value) })}
                            className="w-full rounded-lg border border-white/10 bg-slate-950/70 px-2 py-1.5 text-[12px] text-slate-200"
                          >
                            {[24, 25, 30].map((f) => (
                              <option key={f} value={f}>
                                {f}
                              </option>
                            ))}
                          </select>
                        </Field>
                      </div>

                      <div className="mt-3 grid gap-3 sm:grid-cols-2">
                        <div>
                          <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">Crop</div>
                          <div className="flex flex-wrap gap-1.5">
                            {CROP_MODES.map((m) => (
                              <button
                                key={m.id}
                                onClick={() => setDraft(c.id, { crop: { ...(d.crop || {}), mode: m.id } })}
                                className={`rounded-lg border px-2 py-1 text-[11px] ${
                                  (d.crop?.mode || 'center') === m.id
                                    ? 'border-indigo-400/40 bg-indigo-500/15 text-white'
                                    : 'border-white/10 bg-white/[0.02] text-slate-300'
                                }`}
                              >
                                {m.label}
                              </button>
                            ))}
                          </div>
                          {(d.crop?.mode || 'center') === 'custom' && (
                            <div className="mt-2 grid grid-cols-4 gap-1.5">
                              {(['x', 'y', 'w', 'h'] as const).map((k) => (
                                <label key={k} className="text-[10px] text-slate-500">
                                  {k.toUpperCase()}
                                  <input
                                    type="number"
                                    step="0.01"
                                    min={0}
                                    max={1}
                                    value={d.crop?.[k] ?? 0}
                                    onChange={(e) =>
                                      setDraft(c.id, { crop: { ...(d.crop || {}), mode: 'custom', [k]: Number(e.target.value) } })
                                    }
                                    className="mt-0.5 w-full rounded border border-white/10 bg-slate-950/70 px-1 py-1 text-[10px] text-slate-200"
                                  />
                                </label>
                              ))}
                            </div>
                          )}
                          <p className="mt-1 text-[10px] text-slate-500">
                            Fractions of the source frame. Manual geometry only — no face tracking.
                          </p>
                        </div>

                        <div>
                          <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">Captions</div>
                          <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                            <label className="flex items-center gap-1.5">
                              <input
                                type="checkbox"
                                checked={d.burn_captions}
                                onChange={(e) => setDraft(c.id, { burn_captions: e.target.checked })}
                                className="h-3.5 w-3.5 accent-indigo-500"
                              />
                              Burn captions
                            </label>
                            <select
                              value={d.caption_style?.position || 'bottom'}
                              onChange={(e) =>
                                setDraft(c.id, { caption_style: { ...d.caption_style, position: e.target.value } })
                              }
                              className="rounded border border-white/10 bg-slate-950/70 px-1.5 py-1 text-[11px] text-slate-200"
                            >
                              {POSITIONS.map((p) => (
                                <option key={p} value={p}>
                                  {p}
                                </option>
                              ))}
                            </select>
                            <label className="flex items-center gap-1">
                              size
                              <input
                                type="number"
                                min={20}
                                max={96}
                                value={d.caption_style?.size || 54}
                                onChange={(e) =>
                                  setDraft(c.id, { caption_style: { ...d.caption_style, size: Number(e.target.value) } })
                                }
                                className="w-14 rounded border border-white/10 bg-slate-950/70 px-1 py-1 text-[11px] text-slate-200"
                              />
                            </label>
                            <label className="flex items-center gap-1">
                              max chars
                              <input
                                type="number"
                                min={12}
                                max={60}
                                value={d.caption_style?.max_chars || 32}
                                onChange={(e) =>
                                  setDraft(c.id, { caption_style: { ...d.caption_style, max_chars: Number(e.target.value) } })
                                }
                                className="w-14 rounded border border-white/10 bg-slate-950/70 px-1 py-1 text-[11px] text-slate-200"
                              />
                            </label>
                            <label className="flex items-center gap-1">
                              highlight
                              <input
                                type="color"
                                value={d.caption_style?.highlight || '#FFD166'}
                                onChange={(e) =>
                                  setDraft(c.id, { caption_style: { ...d.caption_style, highlight: e.target.value } })
                                }
                                className="h-6 w-8 rounded border border-white/10 bg-transparent"
                              />
                            </label>
                          </div>

                          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                            <label className="flex items-center gap-1.5">
                              <input
                                type="checkbox"
                                checked={d.audio?.normalize !== false}
                                onChange={(e) => setDraft(c.id, { audio: { ...d.audio, normalize: e.target.checked } })}
                                className="h-3.5 w-3.5 accent-indigo-500"
                              />
                              Normalise loudness
                            </label>
                            <select
                              value={d.audio?.music || ''}
                              onChange={(e) => setDraft(c.id, { audio: { ...d.audio, music: e.target.value || null } })}
                              className="max-w-[160px] rounded border border-white/10 bg-slate-950/70 px-1.5 py-1 text-[11px] text-slate-200"
                            >
                              <option value="">No music</option>
                              {(data?.music || []).map((m) => (
                                <option key={m.path} value={m.path}>
                                  {m.name}
                                </option>
                              ))}
                            </select>
                            {d.audio?.music && (
                              <label className="flex items-center gap-1">
                                vol
                                <input
                                  type="number"
                                  step="0.05"
                                  min={0}
                                  max={1}
                                  value={d.audio?.music_volume ?? 0.18}
                                  onChange={(e) =>
                                    setDraft(c.id, { audio: { ...d.audio, music_volume: Number(e.target.value) } })
                                  }
                                  className="w-14 rounded border border-white/10 bg-slate-950/70 px-1 py-1 text-[11px] text-slate-200"
                                />
                              </label>
                            )}
                          </div>
                          <p className="mt-1 text-[10px] text-slate-500">
                            Music is ducked under speech with a sidechain compressor; output is AAC 48 kHz stereo.
                          </p>
                        </div>
                      </div>

                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <Button
                          variant="primary"
                          disabled={jobRunning}
                          onClick={async () => {
                            setBusy('Saving clip');
                            try {
                              await clipApi.patchClip(c.id, {
                                start_sec: d.start_sec,
                                end_sec: d.end_sec,
                                aspect: d.aspect,
                                preset: d.preset,
                                crop: d.crop,
                                caption_style: d.caption_style,
                                audio: d.audio,
                                burn_captions: d.burn_captions,
                                fps: d.fps,
                              });
                              setDrafts((x) => {
                                const n = { ...x };
                                delete n[c.id];
                                return n;
                              });
                            } catch (e: any) {
                              setErr(String(e.message || e));
                            } finally {
                              setBusy('');
                            }
                            await run('Rendering clip', () =>
                              clipApi.renderClip(c.id, {
                                aspect: d.aspect,
                                preset: d.preset,
                                crop: d.crop,
                                caption_style: d.caption_style,
                                audio: d.audio,
                                burn_captions: d.burn_captions,
                                fps: d.fps,
                              }),
                            );
                          }}
                        >
                          Save & render
                        </Button>
                        <Button
                          variant="subtle"
                          onClick={async () => {
                            await clipApi.regenerateMetadata(c.id);
                            setNotice('Clip copy regenerated from its own transcript text.');
                            reload();
                          }}
                        >
                          Regenerate copy
                        </Button>
                        <span className="text-[11px] text-slate-500">
                          Titles/hooks/hashtags are extracted from the clip transcript (deterministic templates, no LLM).
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Panel>

      <ExportsPanel pid={pid} />

      {data?.jobs?.length ? (
        <Panel>
          <h2 className="text-[15px] font-semibold text-white">Job history</h2>
          <div className="mt-3 space-y-1.5">
            {data.jobs.map((j) => (
              <div key={j.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-white/[0.05] bg-white/[0.02] px-2.5 py-1.5 text-[11px]">
                <Badge tone={statusTone(j.status)}>{j.status}</Badge>
                <span className="text-slate-300">{j.type}</span>
                <span className="text-slate-500">{j.stage}</span>
                <span className="text-slate-400">{j.message}</span>
                <span className="ml-auto text-slate-500">
                  {j.peak_memory_mb ? `${j.peak_memory_mb} MB` : ''} {j.created_at?.slice(11, 19)}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}

function ExportsPanel({ pid }: { pid: string }) {
  const [data, setData] = useState<{ files: { name: string; size_bytes: number; url: string }[]; manifest: any } | null>(null);
  const [err, setErr] = useState('');

  const load = async () => {
    try {
      setData(await clipApi.exports(pid));
      setErr('');
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  };
  useEffect(() => {
    load();
  }, [pid]);

  const items = data?.manifest?.items || [];
  return (
    <Panel>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-[15px] font-semibold text-white">5 · Exports</h2>
          <p className="mt-0.5 text-[12px] text-slate-400">
            Every exported file is measured after writing; failures are listed individually rather than hidden.
          </p>
        </div>
        <Button variant="subtle" onClick={load}>
          Refresh
        </Button>
      </div>
      {err && <div className="mt-2 text-[11px] text-rose-300">{err}</div>}
      {data?.manifest && (
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2 text-[11px] text-slate-400">
            Requested <span className="text-slate-200">{data.manifest.requested}</span>
          </div>
          <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2 text-[11px] text-slate-400">
            Succeeded <span className="text-emerald-300">{data.manifest.succeeded}</span>
          </div>
          <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2 text-[11px] text-slate-400">
            Failed <span className={data.manifest.failed ? 'text-rose-300' : 'text-slate-200'}>{data.manifest.failed}</span>
          </div>
        </div>
      )}
      {!data?.files?.length ? (
        <div className="mt-3">
          <Empty title="No exports yet" hint="Select clips above and use Export to render them into data/clip_projects/<id>/exports." />
        </div>
      ) : (
        <div className="mt-3 space-y-1.5">
          {data.files.map((f) => (
            <div key={f.name} className="flex items-center gap-3 rounded-lg border border-white/[0.05] bg-white/[0.02] px-2.5 py-1.5 text-[11px]">
              <a href={f.url} download className="truncate text-indigo-300 hover:text-indigo-200">
                {f.name}
              </a>
              <span className="ml-auto text-slate-500">{fmtBytes(f.size_bytes)}</span>
            </div>
          ))}
        </div>
      )}
      {items.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-[11px]">
            <thead className="text-[10px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="py-1 pr-3">Clip</th>
                <th className="py-1 pr-3">Aspect</th>
                <th className="py-1 pr-3">Duration</th>
                <th className="py-1 pr-3">Size</th>
                <th className="py-1 pr-3">Hashtags</th>
                <th className="py-1">Validation</th>
              </tr>
            </thead>
            <tbody className="text-slate-300">
              {items.map((it: any, i: number) => (
                <tr key={i} className="border-t border-white/[0.05]">
                  <td className="max-w-[220px] truncate py-1 pr-3">{it.title || it.candidate_id?.slice(0, 8)}</td>
                  <td className="py-1 pr-3">{it.aspect}</td>
                  <td className="py-1 pr-3">{it.duration ? Number(it.duration).toFixed(1) + 's' : '—'}</td>
                  <td className="py-1 pr-3">{fmtBytes(it.size_bytes)}</td>
                  <td className="max-w-[180px] truncate py-1 pr-3 text-slate-500">{(it.hashtags || []).join(' ')}</td>
                  <td className="py-1">
                    {it.error ? (
                      <span className="text-rose-300">failed</span>
                    ) : it.validation?.ok ? (
                      <span className="text-emerald-300">ok</span>
                    ) : (
                      <span className="text-amber-300">check</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
