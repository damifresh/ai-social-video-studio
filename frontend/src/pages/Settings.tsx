import { useEffect, useState } from 'react';
import { api, fmtBytes, SystemT } from '../lib/api';
import { Alert, Badge, Button, Panel, SectionTitle, Spinner } from '../components/ui';

export default function Settings() {
  const [sys, setSys] = useState<SystemT | null>(null);
  const [voices, setVoices] = useState<any[]>([]);
  const [err, setErr] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [audioUrl, setAudioUrl] = useState('');
  const [previewing, setPreviewing] = useState('');

  const load = async () => {
    try {
      const [s, v] = await Promise.all([api.system(), api.voices()]);
      setSys(s);
      setVoices(v.voices || []);
      setErr('');
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl); }, [audioUrl]);

  const preview = async (voice: string) => {
    setPreviewing(voice);
    setErr('');
    try {
      const url = await api.previewVoice(voice, 'This is a local voice preview from your AI Social Video Studio.');
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      setAudioUrl(url);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setPreviewing('');
    }
  };

  const cleanup = async () => {
    setBusy('cleanup');
    setErr('');
    try {
      const r: any = await api.cleanup();
      setNotice(`Removed ${r.removed} temporary files · freed ${r.freed_mb} MB. Project sources and renders were not touched.`);
      load();
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy('');
    }
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setNotice(`Copied: ${text}`);
    } catch {
      setErr('Could not copy to clipboard.');
    }
  };

  const reveal = async (path?: string) => {
    if (!window.desktop) {
      if (path) copy(path);
      return;
    }
    try {
      if (path) await window.desktop.openPath(path);
      else await window.desktop.revealDataFolder();
    } catch (e: any) {
      setErr(String(e.message || e));
    }
  };

  const mem = sys?.memory;
  const memPercent = Number(mem?.percent || 0);

  return (
    <div className="fade-in space-y-6">
      <div>
        <h1 className="text-[30px] font-semibold leading-tight tracking-tight text-white">Settings & system</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-400">
          Everything runs on this machine. There are no accounts, API keys or cloud calls — these panels show exactly what is installed and where your files live.
        </p>
      </div>

      {err && <Alert>{err}</Alert>}
      {notice && !err && <Alert tone="green">{notice}</Alert>}

      {!sys ? (
        <div className="flex items-center gap-3 text-sm text-slate-400"><Spinner /> Reading system state…</div>
      ) : (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            <Panel className="space-y-2 p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Memory</div>
              <div className={`text-2xl font-semibold ${memPercent > 85 ? 'text-rose-300' : memPercent > 70 ? 'text-amber-300' : 'text-emerald-300'}`}>
                {memPercent}% used
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.07]">
                <div className={`h-full rounded-full ${memPercent > 85 ? 'bg-rose-400' : memPercent > 70 ? 'bg-amber-400' : 'bg-emerald-400'}`} style={{ width: `${Math.min(100, memPercent)}%` }} />
              </div>
              <div className="text-[11px] text-slate-500">
                {(Number(mem?.available_mb || 0) / 1024).toFixed(1)} GB free of {(Number(mem?.total_mb || 0) / 1024).toFixed(0)} GB
                {mem?.swap_used_mb ? ` · swap ${mem.swap_used_mb} MB` : ''}
              </div>
              <div className="text-[11px] text-slate-500">Backend RSS: {mem?.process_rss_mb ?? '—'} MB · load {Array.isArray(mem?.load_avg) ? mem.load_avg.join(' / ') : '—'}</div>
            </Panel>

            <Panel className="space-y-2 p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Disk</div>
              <div className="text-2xl font-semibold text-white">{sys.disk?.free_gb ?? '—'} GB free</div>
              <div className="text-[11px] text-slate-500">of {sys.disk?.total_gb ?? '—'} GB · data dir on this volume</div>
              <div className="pt-1">
                <Button variant="subtle" className="px-2 py-1 text-[11px]" onClick={cleanup} disabled={busy === 'cleanup'}>
                  {busy === 'cleanup' ? <Spinner /> : null} Clean temporary files
                </Button>
              </div>
            </Panel>

            <Panel className="space-y-2 p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-slate-500">Library</div>
              <div className="text-2xl font-semibold text-white">{sys.projects.total} projects</div>
              <div className="text-[11px] text-slate-500">{sys.projects.completed} completed · sequential jobs {sys.sequential ? 'on' : 'off'}</div>
              <div className="pt-1">
                <Button variant="subtle" className="px-2 py-1 text-[11px]" onClick={() => reveal()}>
                  {window.desktop ? 'Reveal data folder' : 'Copy data folder path'}
                </Button>
              </div>
            </Panel>
          </div>

          <Panel className="space-y-3 p-5">
            <SectionTitle title="Engines" subtitle="Detected at runtime. Missing engines degrade gracefully and are reported in project metadata." />
            <div className="grid gap-2 sm:grid-cols-2">
              <EngineRow name="FFmpeg" ok={!!sys.engines?.ffmpeg} detail={sys.engines?.ffmpeg || sys.ffmpeg} />
              <EngineRow name="macOS say (TTS)" ok={!!sys.engines?.say} detail={sys.engines?.say ? 'built-in offline voice' : 'not available'} />
              <EngineRow name="Kokoro MLX (TTS)" ok={!!sys.engines?.kokoro} detail={sys.engines?.kokoro ? 'installed' : sys.engines?.kokoro_hint || 'optional'} />
              <EngineRow name="Whisper.cpp (ASR align)" ok={!!sys.engines?.whisper} detail={sys.engines?.whisper ? `${sys.engines?.whisper_model || 'model'} · ${sys.engines?.whisper_bin}` : 'optional — narration timing used by default'} />
              <EngineRow name="Diffusion video" ok={false} detail="disabled by default — not assumed feasible on 8 GB unified memory" />
              <EngineRow name="Python runtime" ok detail={`${sys.python} · ${sys.platform}`} />
            </div>
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel className="space-y-3 p-5">
              <SectionTitle title="Paths" subtitle="Override with LAVS_DATA_DIR, LAVS_ASSETS_DIR, LAVS_MODELS_DIR and LAVS_FRONTEND_DIST." />
              {[
                ['Data', sys.data_dir],
                ['Projects', sys.projects_dir],
                ['Assets', sys.assets_dir],
                ['Models', sys.models_dir],
                ['Database', sys.db_path],
                ['FFmpeg', sys.ffmpeg],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center gap-2 rounded-lg border border-white/[0.05] bg-white/[0.02] px-3 py-2">
                  <span className="w-20 shrink-0 text-[11px] text-slate-500">{label}</span>
                  <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-slate-300" title={value}>{value}</span>
                  <button onClick={() => reveal(value)} className="shrink-0 rounded px-1.5 py-0.5 text-[10px] text-slate-400 hover:bg-white/[0.06] hover:text-white">
                    {window.desktop ? 'Finder' : 'Copy'}
                  </button>
                </div>
              ))}
            </Panel>

            <Panel className="space-y-3 p-5">
              <SectionTitle title="Documentation" subtitle="Installed with the app." />
              {[
                ['README', 'Product overview, quick start and feature map'],
                ['docs/INSTALL.md', 'Fresh machine install, models and packaging'],
                ['docs/DESKTOP_APP.md', 'How the macOS app bundles Python and the backend'],
                ['docs/HARDWARE_LIMITATIONS.md', 'What this M2 / 8 GB machine can and cannot do'],
                ['docs/TROUBLESHOOTING.md', 'Common failures and how to fix them'],
                ['docs/TECHNICAL_DOCUMENTATION.md', 'Pipeline, data model, API reference'],
                ['docs/TEST_REPORT.md', 'Acceptance criteria with measured evidence'],
              ].map(([file, desc]) => (
                <div key={file} className="flex items-start justify-between gap-3 border-b border-white/[0.04] pb-1.5 last:border-0">
                  <div>
                    <div className="font-mono text-[11px] text-slate-300">{file}</div>
                    <div className="text-[10px] text-slate-500">{desc}</div>
                  </div>
                  <span className="text-[10px] text-slate-600">bundled</span>
                </div>
              ))}
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[11px] leading-relaxed text-slate-500">
                Licenses for bundled music and SFX are listed in <span className="font-mono text-slate-400">assets/music/licenses.json</span>. Only distribute media you have rights to use.
              </div>
            </Panel>
          </div>

          <Panel className="space-y-3 p-5">
            <SectionTitle title="Voices" subtitle={`${voices.length} voices detected · previews are generated locally and cached in data/previews`} />
            {audioUrl && <audio autoPlay controls src={audioUrl} className="w-full" />}
            <div className="grid gap-1.5 sm:grid-cols-2">
              {voices.map((v) => (
                <div key={v.id} className="flex items-center justify-between gap-2 rounded-lg border border-white/[0.05] bg-white/[0.02] px-3 py-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-xs text-slate-200">{v.name}</span>
                      <Badge tone={v.available ? 'green' : 'slate'}>{v.engine}</Badge>
                    </div>
                    <div className="truncate text-[10px] text-slate-500">{v.lang}{v.note ? ` · ${v.note}` : ''}</div>
                  </div>
                  <button
                    onClick={() => preview(v.id)}
                    disabled={!v.available || previewing === v.id}
                    className="shrink-0 rounded-lg border border-white/10 px-2 py-1 text-[10px] text-slate-300 hover:bg-white/[0.06] disabled:opacity-40"
                  >
                    {previewing === v.id ? '…' : 'Preview'}
                  </button>
                </div>
              ))}
            </div>
          </Panel>

          <Panel className="space-y-2 p-5 text-[11px] leading-relaxed text-slate-500">
            <h3 className="text-sm font-semibold text-slate-200">Execution policy</h3>
            <ul className="list-disc space-y-1 pl-5">
              <li>One heavy job at a time. Additional requests receive HTTP 409 while a job is running.</li>
              <li>Models and FFmpeg subprocesses are released between stages; intermediates are written to disk.</li>
              <li>Jobs interrupted by a restart are marked <span className="text-violet-300">interrupted</span>; artifacts stay intact and the job can be re-run.</li>
              <li>Output is always 720p H.264 High / AAC 48 kHz in 9:16, 16:9 or 1:1 at 24 or 30 fps.</li>
              <li>Visuals are animated stills and graphics unless generated footage is added explicitly and labeled.</li>
            </ul>
          </Panel>
        </>
      )}
    </div>
  );
}

function EngineRow({ name, ok, detail }: { name: string; ok: boolean; detail: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.05] bg-white/[0.02] px-3 py-2">
      <div className="flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${ok ? 'bg-emerald-400' : 'bg-slate-600'}`} />
        <span className="text-xs text-slate-200">{name}</span>
      </div>
      <span className="max-w-[55%] truncate text-[10px] text-slate-500" title={detail}>{detail}</span>
    </div>
  );
}
