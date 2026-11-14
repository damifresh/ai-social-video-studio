import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../lib/api';
import { Badge, Button, Field, Panel } from '../components/ui';

const STYLES = [
  ['cinematic', 'Cinematic', 'Moody lighting, story-led pacing'],
  ['documentary', 'Documentary', 'Measured, factual narration'],
  ['educational', 'Educational', 'Structured lessons and takeaways'],
  ['explainer', 'Explainer', 'Simple, direct, jargon-free'],
  ['news', 'News', 'Headline-driven, timely'],
  ['motivational', 'Motivational', 'Uplifting, energetic'],
  ['marketing', 'Marketing', 'Persuasive with clear CTA'],
  ['faceless', 'Faceless social', 'Fast captions, no presenter'],
];

const ASPECTS = [
  ['9:16', 'Vertical', 'Reels · TikTok · Shorts', 'aspect-[9/16]'],
  ['16:9', 'Landscape', 'YouTube · web', 'aspect-video'],
  ['1:1', 'Square', 'Feed posts', 'aspect-square'],
];

const TEMPLATES: Record<string, { title: string; topic: string; prompt: string; style: string }> = {
  habits: {
    title: 'Small Habits, Big Results',
    topic: 'How small daily habits compound into extraordinary results',
    prompt: 'Open with a relatable morning moment, explain habit stacking, give 3 practical examples, close with an encouraging CTA.',
    style: 'motivational',
  },
  ocean: {
    title: 'The Hidden Power of Tides',
    topic: 'How ocean tides work and why they matter to coastal life',
    prompt: 'Explain the moon and sun gravitational pull, tidal cycles, and ecological impact with vivid documentary narration.',
    style: 'documentary',
  },
  ai: {
    title: 'AI in 60 Seconds',
    topic: 'What artificial intelligence actually is and how it learns',
    prompt: 'Use a simple analogy, explain training vs inference, and end with one practical everyday example.',
    style: 'explainer',
  },
};

export default function NewProject() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const [voices, setVoices] = useState<any[]>([]);
  const [music, setMusic] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [form, setForm] = useState<any>({
    title: '',
    topic: '',
    prompt: '',
    duration_min: 1,
    aspect_ratio: '16:9',
    style: sp.get('style') || 'cinematic',
    language: 'en',
    voice: 'say:Samantha',
    subtitle_enabled: true,
    music_track: 'none',
    music_volume: 0.1,
    fps: 30,
    burn_subs: true,
    voice_speed: 0,
    auto_mode: true,
    subtitle_style: { font: 'Arial', size: 46, position: 'bottom', primary: '#FFFFFF', highlight: '#FFD166', outline: '#000000', bold: true, keyword_highlight: true, max_chars: 42 },
  });

  useEffect(() => {
    api.voices().then((r) => setVoices(r.voices)).catch(() => {});
    api.music().then((r) => setMusic(r.tracks)).catch(() => {});
    const t = sp.get('template');
    if (t && TEMPLATES[t]) applyTemplate(t);
  }, []);

  const set = (k: string, v: any) => setForm((f: any) => ({ ...f, [k]: v }));
  const setStyle = (k: string, v: any) => setForm((f: any) => ({ ...f, subtitle_style: { ...f.subtitle_style, [k]: v } }));

  function applyTemplate(key: string) {
    const t = TEMPLATES[key];
    if (!t) return;
    setForm((f: any) => ({ ...f, ...t, voice: f.voice, subtitle_style: f.subtitle_style }));
  }

  const submit = async (e: any) => {
    e.preventDefault();
    setErr('');
    if (!form.topic.trim() && !form.prompt.trim()) {
      setErr('Enter a topic or a detailed prompt.');
      return;
    }
    setBusy(true);
    try {
      const body = { ...form, title: form.title.trim() || form.topic.slice(0, 80) || 'Untitled video' };
      const r = await api.createProject(body);
      if (form.auto_mode) {
        await api.generate(r.project.id).catch(() => {});
      }
      nav(`/project/${r.project.id}`);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const sayVoices = voices.filter((v) => v.engine === 'macos-say');
  const kokoro = voices.filter((v) => v.engine === 'kokoro-mlx');
  const kokoroReady = kokoro.some((v) => v.available);

  return (
    <form onSubmit={submit} className="fade-in space-y-6">
      <div>
        <h1 className="text-[30px] font-semibold leading-tight tracking-tight text-white">Create a new video</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-400">
          Describe what you want. The studio writes the script, plans scenes, generates local narration, subtitles and motion — then renders a 720p MP4.
        </p>
      </div>

      {err && <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{err}</div>}

      <div className="grid gap-6 lg:grid-cols-[1.55fr_1fr]">
        <div className="space-y-6">
          <Panel className="space-y-4 p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-200">1 · The idea</h2>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(TEMPLATES).map(([k, t]) => (
                  <button key={k} type="button" onClick={() => applyTemplate(k)} className="rounded-lg border border-white/10 px-2 py-1 text-[11px] text-slate-400 hover:border-indigo-400/40 hover:text-white">
                    {t.title.split(',')[0]}
                  </button>
                ))}
              </div>
            </div>
            <Field label="Video title" hint="Optional — defaults to your topic.">
              <input className="input" value={form.title} onChange={(e) => set('title', e.target.value)} placeholder="e.g. Small Habits, Big Results" />
            </Field>
            <Field label="Topic" hint="One clear sentence works best.">
              <input className="input" value={form.topic} onChange={(e) => set('topic', e.target.value)} placeholder="How small daily habits compound into extraordinary results" />
            </Field>
            <Field label="Detailed prompt" hint="Tone, key points, audience, examples, CTA. Used by the script engine.">
              <textarea className="textarea" value={form.prompt} onChange={(e) => set('prompt', e.target.value)} placeholder="Open with a relatable moment, explain the core idea, give three examples, close with a CTA…" />
            </Field>
          </Panel>

          <Panel className="space-y-4 p-5">
            <h2 className="text-sm font-semibold text-slate-200">2 · Format</h2>
            <Field label="Duration">
              <div className="grid grid-cols-5 gap-2">
                {[1, 2, 3, 4, 5].map((m) => (
                  <button key={m} type="button" onClick={() => set('duration_min', m)}
                    className={`rounded-xl border px-2 py-2.5 text-sm transition ${form.duration_min === m ? 'border-indigo-400/50 bg-indigo-500/15 text-white' : 'border-white/10 bg-white/[0.02] text-slate-400 hover:text-white'}`}>
                    {m} min
                  </button>
                ))}
              </div>
            </Field>
            <Field label="Aspect ratio">
              <div className="grid grid-cols-3 gap-2">
                {ASPECTS.map(([id, label, sub]) => (
                  <button key={id} type="button" onClick={() => set('aspect_ratio', id)}
                    className={`rounded-xl border p-2.5 text-left transition ${form.aspect_ratio === id ? 'border-indigo-400/50 bg-indigo-500/15' : 'border-white/10 bg-white/[0.02] hover:border-white/20'}`}>
                    <span className={`mx-auto mb-2 block w-5 rounded-sm border ${form.aspect_ratio === id ? 'border-indigo-300 bg-indigo-400/30' : 'border-slate-600'}`} style={{ aspectRatio: id.replace(':', '/') }} />
                    <div className="text-xs font-medium text-slate-200">{label}</div>
                    <div className="text-[10px] text-slate-500">{sub}</div>
                  </button>
                ))}
              </div>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Frame rate">
                <select className="select" value={form.fps} onChange={(e) => set('fps', Number(e.target.value))}>
                  <option value={30}>30 fps</option>
                  <option value={24}>24 fps</option>
                </select>
              </Field>
              <Field label="Resolution">
                <input className="input opacity-70" value="720p · H.264 / AAC" disabled />
              </Field>
            </div>
            <Field label="Video style">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {STYLES.map(([id, name]) => (
                  <button key={id} type="button" onClick={() => set('style', id)}
                    className={`rounded-xl border px-2 py-2 text-xs transition ${form.style === id ? 'border-indigo-400/50 bg-indigo-500/15 text-white' : 'border-white/10 text-slate-400 hover:text-white'}`}>
                    {name}
                  </button>
                ))}
              </div>
            </Field>
          </Panel>

          <Panel className="space-y-4 p-5">
            <h2 className="text-sm font-semibold text-slate-200">3 · Narration</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Voice" hint={kokoroReady ? 'Kokoro MLX detected.' : 'Kokoro not installed — macOS voices work fully offline.'}>
                <select className="select" value={form.voice} onChange={(e) => set('voice', e.target.value)}>
                  <optgroup label="macOS · offline">
                    {sayVoices.map((v) => <option key={v.id} value={v.id}>{v.name} ({v.lang})</option>)}
                  </optgroup>
                  <optgroup label={kokoroReady ? 'Kokoro MLX' : 'Kokoro MLX (not installed)'}>
                    {kokoro.map((v) => <option key={v.id} value={v.id} disabled={!v.available}>{v.name}</option>)}
                  </optgroup>
                </select>
              </Field>
              <Field label="Language">
                <input className="input" value={form.language} onChange={(e) => set('language', e.target.value)} placeholder="en" />
              </Field>
            </div>
            <Field label={`Speech rate offset: ${form.voice_speed > 0 ? '+' : ''}${form.voice_speed}`} hint="0 = natural. Positive values speak faster on macOS voices.">
              <input type="range" min={-60} max={80} step={5} value={form.voice_speed} onChange={(e) => set('voice_speed', Number(e.target.value))} className="w-full" />
            </Field>
            {!kokoroReady && (
              <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[11px] leading-relaxed text-slate-500">
                Kokoro MLX weights are downloaded separately and run one model at a time. If unavailable, narration is generated with the built-in macOS voice and the fallback is recorded in the result metadata — never silently.
              </div>
            )}
          </Panel>
        </div>

        <div className="space-y-6">
          <Panel className="space-y-4 p-5">
            <h2 className="text-sm font-semibold text-slate-200">4 · Subtitles</h2>
            <label className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2.5">
              <span className="text-sm text-slate-300">Generate subtitles</span>
              <input type="checkbox" checked={form.subtitle_enabled} onChange={(e) => set('subtitle_enabled', e.target.checked)} className="h-4 w-4 accent-indigo-500" />
            </label>
            <label className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2.5">
              <span className="text-sm text-slate-300">Burn captions into video</span>
              <input type="checkbox" checked={form.burn_subs} onChange={(e) => set('burn_subs', e.target.checked)} className="h-4 w-4 accent-indigo-500" />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Position">
                <select className="select" value={form.subtitle_style.position} onChange={(e) => setStyle('position', e.target.value)}>
                  <option value="bottom">Bottom</option>
                  <option value="center">Center</option>
                  <option value="top">Top</option>
                </select>
              </Field>
              <Field label="Font size">
                <input type="number" className="input" value={form.subtitle_style.size} onChange={(e) => setStyle('size', Number(e.target.value))} min={20} max={96} />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Text color">
                <input type="color" className="input h-10 p-1" value={form.subtitle_style.primary} onChange={(e) => setStyle('primary', e.target.value)} />
              </Field>
              <Field label="Highlight color">
                <input type="color" className="input h-10 p-1" value={form.subtitle_style.highlight} onChange={(e) => setStyle('highlight', e.target.value)} />
              </Field>
            </div>
            <label className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2.5">
              <span className="text-sm text-slate-300">Highlight keywords</span>
              <input type="checkbox" checked={form.subtitle_style.keyword_highlight} onChange={(e) => setStyle('keyword_highlight', e.target.checked)} className="h-4 w-4 accent-indigo-500" />
            </label>
          </Panel>

          <Panel className="space-y-4 p-5">
            <h2 className="text-sm font-semibold text-slate-200">5 · Music</h2>
            <Field label="Background track" hint="Only properly licensed audio. Add files to assets/music with a licenses.json entry.">
              <select className="select" value={form.music_track} onChange={(e) => set('music_track', e.target.value)}>
                <option value="none">None — narration only</option>
                {music.filter((m) => m.kind === 'music').map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
              </select>
            </Field>
            {music.length === 0 && <div className="text-[11px] text-slate-500">No bundled tracks. The mix engine supports ducking, loops and fades when you add your own.</div>}
            <Field label={`Music level: ${Math.round(form.music_volume * 100)}%`} hint="Music automatically ducks under narration.">
              <input type="range" min={0} max={0.5} step={0.01} value={form.music_volume} onChange={(e) => set('music_volume', Number(e.target.value))} className="w-full" />
            </Field>
          </Panel>

          <Panel className="space-y-3 p-5">
            <h2 className="text-sm font-semibold text-slate-200">6 · Workflow</h2>
            <label className="flex items-start justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2.5">
              <span>
                <span className="block text-sm text-slate-300">Automatic mode</span>
                <span className="block text-[11px] text-slate-500">Start the full pipeline immediately after creating the project.</span>
              </span>
              <input type="checkbox" checked={form.auto_mode} onChange={(e) => set('auto_mode', e.target.checked)} className="mt-0.5 h-4 w-4 accent-indigo-500" />
            </label>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-[11px] leading-relaxed text-slate-500">
              Manual mode lets you review and edit the script and storyboard before the first render. Jobs always run sequentially on this 8 GB machine.
            </div>
          </Panel>

          <Button type="submit" variant="primary" disabled={busy} className="w-full py-3 text-[15px]">
            {busy ? 'Creating…' : form.auto_mode ? 'Create & generate video' : 'Create project'}
          </Button>
          <div className="text-center text-[11px] text-slate-600">
            <Badge>100% local</Badge> <span className="mx-1">·</span> No cloud inference <span className="mx-1">·</span> Zero API cost
          </div>
        </div>
      </div>
    </form>
  );
}
