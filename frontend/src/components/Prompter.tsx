import { useEffect, useState } from 'react';
import { clipApi } from '../lib/api';
import { Badge, Button } from './ui';

export const PROMPT_IDEAS = [
  'Funny 15s TikTok clips about habits; avoid jargon',
  'Educational clips for beginners; clear audio and complete thoughts',
  'Motivational LinkedIn clips about discipline; no controversial claims',
];

type PresetT = { id: string; label: string; instruction: string; default_prompt: string };

export default function Prompter({
  value,
  onChange,
  preset,
  onPresetChange,
  singleClip,
  onSingleClipChange,
  captions,
  onCaptionsChange,
  transitions,
  onTransitionsChange,
  projectId,
}: {
  value: string;
  onChange: (value: string) => void;
  preset: string;
  onPresetChange: (preset: string) => void;
  singleClip: boolean;
  onSingleClipChange: (enabled: boolean) => void;
  captions: boolean;
  onCaptionsChange: (enabled: boolean) => void;
  transitions: boolean;
  onTransitionsChange: (enabled: boolean) => void;
  projectId?: string;
}) {
  const [presets, setPresets] = useState<PresetT[]>([]);
  const [brief, setBrief] = useState<any>(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    clipApi.directorPresets().then((r) => setPresets(r.presets)).catch(() => {});
  }, []);

  const clear = () => {
    setBrief(null);
    setError('');
    setStatus('');
  };

  const update = (next: string) => {
    onChange(next);
    clear();
  };

  const choosePreset = (id: string) => {
    onPresetChange(id);
    if (!value.trim()) {
      const item = presets.find((p) => p.id === id);
      if (item) onChange(item.default_prompt);
    }
    clear();
  };

  const preview = async () => {
    if (!value.trim()) return;
    setBusy(true);
    setError('');
    setStatus('');
    try {
      if (projectId) {
        const result = await clipApi.previewDirection(projectId, {
          prompt: value,
          preset,
          single_clip: singleClip,
        });
        setBrief(result.brief);
        setStatus(result.notice);
      } else {
        const result = await clipApi.parsePrompt(value, preset, singleClip);
        setBrief(result.brief);
        setStatus('Local director rules parsed the brief.');
      }
    } catch (e: any) {
      setBrief(null);
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 rounded-xl border border-indigo-500/15 bg-indigo-500/[0.04] p-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[12px] font-semibold text-white">Prompter · describe the outcome</div>
          <p className="mt-0.5 text-[11px] text-slate-400">
            The local director parses your brief into transparent, transcript-grounded scoring rules. Turn on{' '}
            <strong>One clip</strong> to assemble one final short video from several ordered transcript scenes; pauses
            and scene cuts support the boundaries.
            <strong> Captions</strong> burns transcript-grounded subtitles into generated clips and combined videos (from each source's own transcript).
            Upload several videos to combine them; <strong>Transitions</strong> chooses smooth crossfades or straightforward cuts.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            data-testid="prompter-single-toggle"
            aria-pressed={singleClip}
            title="One final video: the director orders several transcript-grounded scenes into one short"
            onClick={() => {
              onSingleClipChange(!singleClip);
              clear();
            }}
            className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
              singleClip
                ? 'border-emerald-400/40 bg-emerald-500/15 text-emerald-200'
                : 'border-white/10 bg-white/[0.02] text-slate-400 hover:border-emerald-400/30 hover:text-slate-200'
            }`}
          >
            One clip: {singleClip ? 'on' : 'off'}
          </button>
          <button
            type="button"
            data-testid="prompter-captions-toggle"
            aria-pressed={captions}
            title="Burn transcript-grounded captions into generated clips; combine outputs have no transcript captions"
            onClick={() => {
              onCaptionsChange(!captions);
              clear();
            }}
            className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
              captions
                ? 'border-amber-400/40 bg-amber-500/15 text-amber-200'
                : 'border-white/10 bg-white/[0.02] text-slate-400 hover:border-amber-400/30 hover:text-slate-200'
            }`}
          >
            Captions: {captions ? 'on' : 'off'}
          </button>
          <button
            type="button"
            data-testid="prompter-transitions-toggle"
            aria-pressed={transitions}
            title="Smooth crossfades between combined videos; turn off for straightforward cuts"
            onClick={() => {
              onTransitionsChange(!transitions);
              clear();
            }}
            className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
              transitions
                ? 'border-sky-400/40 bg-sky-500/15 text-sky-200'
                : 'border-white/10 bg-white/[0.02] text-slate-400 hover:border-sky-400/30 hover:text-slate-200'
            }`}
          >
            Transitions: {transitions ? 'smooth' : 'cut'}
          </button>
          <Badge tone="indigo">local director</Badge>
          {singleClip ? <Badge tone="green">auto-clip · 1 video</Badge> : null}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Set prompt</span>
        {presets.map((item) => (
          <button
            key={item.id}
            type="button"
            data-testid="prompter-preset"
            aria-pressed={preset === item.id}
            title={item.instruction}
            onClick={() => choosePreset(item.id)}
            className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
              preset === item.id
                ? 'border-violet-400/40 bg-violet-500/15 text-violet-200'
                : 'border-white/10 bg-white/[0.02] text-slate-400 hover:border-violet-400/30 hover:text-slate-200'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="mt-2 flex items-start gap-2">
        <textarea
          data-testid="prompter-input"
          rows={3}
          value={value}
          onChange={(e) => update(e.target.value)}
          placeholder="e.g. Funny 15s clips for TikTok about habits; avoid jargon and keep complete thoughts"
          className="min-h-[72px] flex-1 resize-y rounded-xl border border-white/10 bg-slate-950/60 px-3 py-2 text-[13px] text-slate-100 outline-none placeholder:text-slate-600 focus:border-indigo-400/40"
        />
        <Button variant="subtle" onClick={preview} disabled={!value.trim() || busy}>
          {busy ? 'Parsing…' : 'Preview'}
        </Button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {PROMPT_IDEAS.map((idea) => (
          <button
            key={idea}
            type="button"
            data-testid="prompter-chip"
            onClick={() => update(idea)}
            className="rounded-full border border-white/10 bg-white/[0.02] px-2.5 py-1 text-[11px] text-slate-400 transition hover:border-indigo-400/30 hover:text-slate-200"
          >
            {idea}
          </button>
        ))}
      </div>
      {(brief || error || status) && (
        <div className="mt-2 rounded-lg border border-white/[0.06] bg-slate-950/50 px-3 py-2 text-[11px] text-slate-300">
          {error ? (
            <span className="text-rose-300">{error}</span>
          ) : (
            <>
              <div><span className="text-slate-500">Parsed:</span> {brief?.summary}</div>
              {!!brief?.rules?.length && (
                <div className="mt-1 text-slate-500">Modifiers · {brief.rules.join(' · ')}</div>
              )}
              {!!status && <div className="mt-1 text-indigo-300/80">{status}</div>}
            </>
          )}
        </div>
      )}
    </div>
  );
}
