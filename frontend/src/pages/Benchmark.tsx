import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import { Badge, Button, Empty, Panel, SectionTitle, Spinner, statusTone } from '../components/ui';

function num(v: any, digits = 1) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return n.toFixed(digits).replace(/\.0+$/, '');
}

function pretty(v: any) {
  return <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950/70 p-3 text-[11px] leading-relaxed text-slate-300">{JSON.stringify(v, null, 2)}</pre>;
}

export default function Benchmark() {
  const [env, setEnv] = useState<any>(null);
  const [sample, setSample] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [active, setActive] = useState<any>(null);
  const [selected, setSelected] = useState<any>(null);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [notice, setNotice] = useState('');

  const load = async () => {
    try {
      const [e, r] = await Promise.all([api.benchmarkEnv().catch(() => null), api.benchmarkRuns().catch(() => ({ runs: [], active: null }))]);
      if (e) setEnv(e);
      setRuns(r.runs || []);
      setActive(r.active || null);
      setErr('');
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  };

  const loadSample = async () => {
    try {
      const s = await api.benchmarkSample();
      setSample(s);
    } catch {
      /* ignore transient sample errors */
    }
  };

  useEffect(() => {
    load();
    loadSample();
    const t = setInterval(() => { load(); loadSample(); }, 2500);
    return () => clearInterval(t);
  }, []);

  const latest = runs[0];
  useEffect(() => {
    if (!selected && latest?.id) {
      api.benchmarkRun(latest.id).then(setSelected).catch(() => {});
    }
  }, [latest?.id]);

  const openRun = async (id: string) => {
    try {
      setBusy(`open:${id}`);
      setSelected(await api.benchmarkRun(id));
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy('');
    }
  };

  const startBaseline = async () => {
    setErr(''); setNotice('');
    try {
      setBusy('start');
      await api.benchmarkStartBaseline({ title: 'Engine A Baseline (UI)' });
      setNotice('Baseline started. Runs execute real Engine A generations sequentially; results/reports appear when complete.');
      await load();
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy('');
    }
  };

  const mem = sample?.system_memory;
  const appMem = sample?.app_memory;
  const gpu = sample?.gpu;

  return (
    <div className="fade-in space-y-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-indigo-300/80">M2 Hardware Benchmark</div>
          <h1 className="text-[30px] font-semibold leading-tight tracking-tight text-white">M2 HARDWARE BENCHMARK</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-400">
            Measured benchmark instrumentation for local engines on Apple M2 / 8 GB. Runs record real metrics and outputs; unavailable capabilities (e.g. Engine B auto-clip, WER ground truth, human highlight ratings) are reported as not implemented/not run — never fabricated.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="primary" onClick={startBaseline} disabled={busy === 'start' || active?.running}>
            {busy === 'start' ? <Spinner /> : null} {active?.running ? 'Benchmark running…' : 'Run Engine A Baseline'}
          </Button>
        </div>
      </div>

      {err && <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{err}</div>}
      {notice && !err && <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">{notice}</div>}

      <section>
        <SectionTitle title="Live measurements" subtitle="Sampled during/around benchmarks (sources shown). Application memory is process-tree RSS, not total system memory." />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Metric label="CPU utilization" value={`${num(sample?.cpu_percent, 1)}%`} hint="psutil.cpu_percent" />
          <Metric label="Application memory (RSS)" value={`${num(appMem?.rss_mb, 1)} MB`} hint={appMem?.source || 'process tree RSS'} />
          <Metric label="System memory used" value={`${num(mem?.percent, 1)}%`} hint={`${num(mem?.used_mb, 0)} / ${num(mem?.total_mb, 0)} MB`} />
          <Metric label="Swap used" value={`${num(sample?.swap?.used_mb, 0)} MB`} hint={`${num(sample?.swap?.percent, 1)}% of ${num(sample?.swap?.total_mb, 0)} MB`} />
          <Metric label="Available disk" value={`${num(sample?.disk?.free_gb, 2)} GB`} hint={`of ${num(sample?.disk?.total_gb, 1)} GB`} />
          <Metric label="Memory pressure" value={sample?.memory_pressure?.level || '—'} hint={sample?.memory_pressure?.available ? 'memory_pressure (best-effort)' : sample?.memory_pressure?.source || '—'} />
          <Metric label="GPU/Metal activity" value={gpu?.available ? 'sampled' : 'unavailable'} hint={gpu?.source || gpu?.note || 'not reliably measurable'} />
          <Metric label="Benchmark status" value={active?.running ? 'running' : 'idle'} hint={active?.message || (runs[0]?.status || 'no runs yet')} />
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
        <Panel className="space-y-3 p-5">
          <SectionTitle title="Test environment" subtitle="Captured configuration and versions (recorded per run/report)." />
          {!env ? <div className="text-sm text-slate-500"><Spinner /> Loading…</div> : (
            <div className="grid gap-2 text-xs">
              <Row k="macOS" v={`${env.software?.platform || ''} · ${env.software?.macos_version || ''}`} />
              <Row k="Processor" v={`${env.hardware?.processor || ''} (${env.hardware?.cpu_logical || '?'} logical)`} />
              <Row k="Memory" v={`${env.hardware?.memory_gb || '?'} GB unified`} />
              <Row k="Disk free" v={`${env.disk?.free_gb || '?'} GB / ${env.disk?.total_gb || '?'} GB`} />
              <Row k="App/Git" v={`${env.software?.app_version || ''} · ${env.software?.git?.short || '—'} ${env.software?.git?.dirty ? '(dirty)' : ''}`} />
              <Row k="FFmpeg" v={(env.software?.ffmpeg_version || env.config?.ffmpeg || '').slice(0, 90)} />
              <Row k="Engines" v={`say=${String(env.software?.engines?.say)} kokoro=${String(env.software?.engines?.kokoro)} whisper=${String(env.software?.engines?.whisper)}`} />
              <Row k="HW accel / config" v="Sequential pipeline, 720p target, disk-backed intermediates; GPU utilization not auto-sampled" />
            </div>
          )}
        </Panel>

        <Panel className="space-y-3 p-5">
          <SectionTitle title="Benchmark runs" subtitle="Measured runs with JSON/HTML reports." />
          {runs.length === 0 ? <div className="text-sm text-slate-500">No benchmark runs yet. Start a baseline to collect real Engine A measurements.</div> : (
            <div className="space-y-2">
              {runs.slice(0, 8).map((r) => (
                <button key={r.id} onClick={() => openRun(r.id)} className={`w-full rounded-xl border px-3 py-2 text-left transition ${selected?.id === r.id ? 'border-indigo-400/40 bg-indigo-500/10' : 'border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.04]'}`}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm text-slate-200">{r.title || r.suite || r.id}</div>
                      <div className="text-[11px] text-slate-500">{r.updated_at ? new Date(r.updated_at).toLocaleString() : ''} · {r.id}</div>
                    </div>
                    <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Panel className="space-y-4 p-5">
        <SectionTitle title="Selected run details" subtitle="Actual measured results. Engine B and unavailable datasets are reported honestly." />
        {!selected ? <div className="text-sm text-slate-500">Select a run to view details.</div> : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <Badge tone={statusTone(selected.status)}>{selected.status}</Badge>
              <span>{selected.title}</span>
              <span className="text-slate-600">·</span>
              <span>{selected.id}</span>
              {selected.reports?.html && <span className="text-slate-500">HTML report: <span className="font-mono text-slate-300">{selected.reports.html.split('/').slice(-2).join('/')}</span></span>}
              {selected.reports?.json && <span className="text-slate-500">JSON report: <span className="font-mono text-slate-300">{selected.reports.json.split('/').slice(-2).join('/')}</span></span>}
            </div>

            {selected.summary && pretty(selected.summary)}

            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-200">AI Video Creator tests (measured)</h3>
              <div className="space-y-2">
                {(selected.tests || []).map((t: any) => (
                  <div key={t.id} className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-sm font-medium text-slate-200">{t.id} · {t.name}</div>
                      <Badge tone={statusTone(t.status)}>{t.status}</Badge>
                    </div>
                    <div className="mt-2 grid gap-1 text-[11px] text-slate-400 sm:grid-cols-2 lg:grid-cols-3">
                      <div>Wall time: <span className="text-slate-200">{num(t.wall_time_sec, 2)} s</span></div>
                      <div>Output duration: <span className="text-slate-200">{num(t.output_duration_sec, 2)} s</span></div>
                      <div>Processing ratio: <span className="text-slate-200">{num(t.processing_speed_ratio, 3)}x</span></div>
                      <div>Peak app RSS: <span className="text-slate-200">{num(t.peak_app_rss_mb, 1)} MB</span></div>
                      <div>Swap peak: <span className="text-slate-200">{num(t.swap_used_mb_peak, 0)} MB</span></div>
                      <div>CPU avg/peak: <span className="text-slate-200">{num(t.cpu_percent_avg, 1)} / {num(t.cpu_percent_peak, 1)}%</span></div>
                      <div>Export size: <span className="text-slate-200">{t.export_size_bytes ? `${(t.export_size_bytes / 1048576).toFixed(2)} MB` : '—'}</span></div>
                      <div>Resolution/FPS: <span className="text-slate-200">{t.resolution || '—'} / {t.fps || '—'}</span></div>
                      <div>Scenes/cues: <span className="text-slate-200">{t.scenes ?? '—'} / {t.subtitle_cues ?? '—'}</span></div>
                      <div>Export valid: <span className="text-slate-200">{String(t.export_validation?.ok)}</span></div>
                      <div>TTS engines: <span className="text-slate-200">{(t.tts_engines || []).join(', ') || '—'}</span></div>
                      <div>Project: <span className="font-mono text-slate-300">{t.project_id || '—'}</span></div>
                    </div>
                    {t.notes && <div className="mt-2 text-[11px] text-slate-500">{t.notes}</div>}
                    {t.warnings?.length ? <div className="mt-2 text-[11px] text-amber-300">Warnings: {t.warnings.join('; ')}</div> : null}
                  </div>
                ))}
              </div>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <h3 className="mb-2 text-sm font-semibold text-slate-200">AI Auto-Clip / accuracy / highlight (honest status)</h3>
                {pretty({
                  auto_clip_results: selected.sections?.auto_clip_results,
                  transcription_accuracy: selected.sections?.transcription_accuracy,
                  highlight_quality: selected.sections?.highlight_quality,
                })}
              </div>
              <div>
                <h3 className="mb-2 text-sm font-semibold text-slate-200">Memory, stability, bottlenecks, recommendations</h3>
                {pretty({
                  memory_performance: selected.sections?.memory_performance,
                  stability_results: selected.sections?.stability_results,
                  bottleneck_analysis: selected.sections?.bottleneck_analysis,
                  optimization_recommendations: selected.sections?.optimization_recommendations,
                  failed_tests: selected.sections?.failed_tests,
                })}
              </div>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-200">Hardware capability classification & final assessment</h3>
              {pretty({
                classification: selected.sections?.hardware_capability_classification,
                final_assessment: selected.sections?.final_assessment,
                known_limitations: selected.sections?.known_limitations,
              })}
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <Panel className="px-4 py-3.5">
      <div className="text-[11px] uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className="mt-1 text-xl font-semibold tracking-tight text-white">{value}</div>
      <div className="mt-0.5 text-[10px] leading-snug text-slate-500">{hint}</div>
    </Panel>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-white/[0.04] pb-1.5">
      <span className="shrink-0 text-slate-500">{k}</span>
      <span className="text-right text-slate-300">{v}</span>
    </div>
  );
}
