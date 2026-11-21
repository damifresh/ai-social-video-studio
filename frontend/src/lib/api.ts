const BASE = '';

async function req<T = any>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const t = await r.text();
      try {
        const j = JSON.parse(t);
        detail = j.detail || t;
      } catch {
        detail = t || detail;
      }
    } catch {
      /* ignore */
    }
    throw new Error(`${r.status} ${detail}`);
  }
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('application/json')) return r.json() as Promise<T>;
  return (await r.text()) as unknown as T;
}

export type JobT = {
  id: string;
  project_id: string;
  type: string;
  stage: string;
  status: string;
  progress: number;
  message: string;
  error?: string | null;
  meta?: any;
  peak_memory_mb?: number;
  elapsed_sec?: number | null;
  eta_sec?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type ProjectT = {
  id: string;
  title: string;
  topic: string;
  prompt: string;
  duration_min: number;
  aspect_ratio: string;
  resolution: string;
  style: string;
  language: string;
  voice: string;
  subtitle_enabled: boolean;
  music_track: string;
  status: string;
  fps: number;
  burn_subs: boolean;
  subtitle_style: Record<string, any>;
  music_volume: number;
  voice_speed: number;
  auto_mode: boolean;
  thumbnail?: string;
  created_at?: string;
  updated_at?: string;
  duration_sec?: number | null;
};

export type SceneT = {
  index?: number;
  title?: string;
  narration: string;
  visual_description?: string;
  duration_sec?: number;
  actual_audio_dur?: number;
  render_dur?: number;
  camera?: string;
  transition?: string;
  sfx?: string;
  text_overlay?: string;
  image_path?: string;
  audio_path?: string;
  video_path?: string;
  visual_kind?: string;
  tts_engine?: string;
  tts_voice?: string;
  tts_fallback?: string;
  tts_fallback_reason?: string;
};

export type CueT = { start: number; end: number; text: string; scene?: number };

export type ProjectDetailT = {
  project: ProjectT;
  script: any;
  scenes: SceneT[];
  result: any;
  timings: any;
  subtitles: CueT[];
  history: any[];
};

export type SystemT = {
  app: string;
  version: string;
  python: string;
  platform: string;
  data_dir: string;
  projects_dir: string;
  assets_dir: string;
  models_dir: string;
  db_path: string;
  ffmpeg: string;
  engines: Record<string, any>;
  memory: Record<string, any>;
  disk: Record<string, any>;
  projects: { total: number; completed: number };
  running_job: string | null;
  sequential: boolean;
};

export const api = {
  health: () => req('/health'),
  system: () => req<SystemT>('/api/system'),
  cleanup: () => req('/api/system/cleanup', { method: 'POST' }),

  voices: () => req<{ voices: any[] }>('/api/voices'),
  previewVoice: async (voice: string, text?: string): Promise<string> => {
    const r = await fetch('/api/voices/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ voice, text }),
    });
    if (!r.ok) throw new Error(await r.text());
    const blob = await r.blob();
    return URL.createObjectURL(blob);
  },

  projects: () => req<{ projects: ProjectT[] }>('/api/projects'),
  project: (id: string) => req<ProjectDetailT>(`/api/projects/${id}`),
  timeline: (id: string) => req(`/api/projects/${id}/timeline`),
  createProject: (body: any) => req<{ project: ProjectT }>('/api/projects', { method: 'POST', body: JSON.stringify(body) }),
  updateProject: (id: string, body: any) => req<{ project: ProjectT }>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteProject: (id: string, deleteFiles = false) => req(`/api/projects/${id}?delete_files=${deleteFiles}`, { method: 'DELETE' }),
  duplicateProject: (id: string) => req<{ project: ProjectT }>(`/api/projects/${id}/duplicate`, { method: 'POST' }),

  generateScript: (id: string) => req(`/api/projects/${id}/generate-script`, { method: 'POST' }),
  saveScript: (id: string, body: any) => req(`/api/projects/${id}/script`, { method: 'PUT', body: JSON.stringify(body) }),
  saveScenes: (id: string, scenes: SceneT[]) => req(`/api/projects/${id}/scenes`, { method: 'PUT', body: JSON.stringify({ scenes }) }),
  reorderScenes: (id: string, order: number[]) => req(`/api/projects/${id}/scenes/reorder`, { method: 'POST', body: JSON.stringify({ order }) }),
  regenScene: (id: string, idx: number) => req<{ job: JobT }>(`/api/projects/${id}/scenes/${idx}/regenerate`, { method: 'POST' }),
  uploadSceneImage: async (id: string, idx: number, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch(`/api/projects/${id}/scenes/${idx}/image`, { method: 'POST', body: fd });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  generate: (id: string) => req<{ job: JobT }>(`/api/projects/${id}/generate`, { method: 'POST' }),
  rerender: (id: string, burn?: boolean) =>
    req<{ job: JobT }>(`/api/projects/${id}/rerender${burn === undefined ? '' : `?burn_subs=${burn}`}`, { method: 'POST' }),
  job: (id: string) => req<{ job: JobT }>(`/api/jobs/${id}`),
  cancelJob: (id: string) => req(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  projectJobs: (id: string) => req<{ jobs: JobT[] }>(`/api/projects/${id}/jobs`),

  subtitles: (id: string) => req<{ segments: CueT[]; style: any }>(`/api/projects/${id}/subtitles`),
  saveSubtitles: (id: string, segments: CueT[], style?: any) =>
    req(`/api/projects/${id}/subtitles`, { method: 'PUT', body: JSON.stringify({ segments, style }) }),

  projectAssets: (id: string) => req<{ images: any[]; audio: any[]; other: any[] }>(`/api/projects/${id}/assets`),
  uploadAsset: async (id: string, kind: string, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch(`/api/projects/${id}/assets/upload?kind=${kind}`, { method: 'POST', body: fd });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  music: () => req<{ tracks: any[] }>('/api/music'),
  library: (kind?: string) => req<{ items: any[]; bundled: any[]; count: number }>(`/api/library${kind ? `?kind=${encodeURIComponent(kind)}` : ''}`),
  exports: () => req<{ exports: any[] }>('/api/exports'),

  benchmarkEnv: () => req<any>('/api/benchmark/environment'),
  benchmarkSample: () => req<any>('/api/benchmark/sample'),
  benchmarkRuns: () => req<any>('/api/benchmark/runs'),
  benchmarkRun: (id: string) => req<any>(`/api/benchmark/runs/${id}`),
  benchmarkStartBaseline: (body?: any) => req<any>('/api/benchmark/run/baseline', { method: 'POST', body: JSON.stringify(body || {}) }),

  fileUrl: (pid: string, kind: string) => `/api/projects/${pid}/files/${kind}`,
  assetUrl: (pid: string, rel: string) => `/api/projects/${pid}/asset/${rel}`,
  thumbUrl: (pid: string, cacheKey?: string) => `/api/projects/${pid}/files/thumbnail${cacheKey ? `?v=${cacheKey}` : ''}`,
};

export function fmtDuration(sec?: number | null): string {
  if (!sec || sec <= 0) return '—';
  const s = Math.round(sec);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

export function fmtBytes(n?: number | null): string {
  if (!n || n <= 0) return '—';
  if (n > 1024 ** 3) return `${(n / 1024 ** 3).toFixed(2)} GB`;
  if (n > 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024).toFixed(0)} KB`;
}

// ---------------------------------------------------------------------------
// Engine B (AI Auto-Clip Studio)
// ---------------------------------------------------------------------------

export type ClipJobT = {
  id: string;
  clip_project_id: string;
  type: string;
  stage: string;
  status: string;
  progress: number;
  message: string;
  error?: string | null;
  canceled: boolean;
  peak_memory_mb: number;
  meta?: any;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export type ClipSourceT = {
  id: string;
  original_name: string;
  ext: string;
  sha256: string;
  size_bytes: number;
  duration_sec: number;
  width: number;
  height: number;
  fps: number;
  vcodec: string;
  acodec: string;
  audio_streams: number;
  sample_rate: number;
  channels: number;
  probe?: any;
  created_at?: string | null;
  url: string;
};

export type ClipEditT = {
  aspect?: string;
  preset?: string;
  crop?: { mode?: string; x?: number; y?: number; w?: number; h?: number } | null;
  caption_style?: Record<string, any>;
  audio?: { normalize?: boolean; music?: string | null; music_volume?: number };
  burn_captions?: boolean;
  fps?: number;
};

export type ClipRenderT = {
  id: string;
  aspect_ratio: string;
  preset: string;
  duration_sec: number;
  size_bytes: number;
  state: string;
  probe?: any;
  url: string;
};

export type ClipCandidateT = {
  id: string;
  clip_project_id: string;
  start_sec: number;
  end_sec: number;
  duration_sec: number;
  transcript_text: string;
  title: string;
  hook: string;
  category: string;
  score: number;
  score_json?: {
    components?: Record<string, { raw: number; weight: number; contribution: number }>;
    metrics?: Record<string, any>;
    weights?: Record<string, number>;
    params?: any;
    copy?: any;
    assembly?: any;
    segments?: any[];
  } | null;
  copy?: any;
  assembly?: any;
  segments?: any[];
  reason: string;
  selected: boolean;
  state: string;
  edit: ClipEditT;
  renders: ClipRenderT[];
};

export type ClipProjectT = {
  id: string;
  title: string;
  status: string;
  aspect_ratio: string;
  preset: string;
  language: string;
  settings: Record<string, any>;
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  source: ClipSourceT | null;
  sources: ClipSourceT[];
  source_count: number;
  transitions: boolean;
  burn_captions: boolean;
  counts: { clips: number; rendered: number };
  transcript: { present: boolean; backend?: string | null; timing?: string | null; sentences?: number } | null;
  analysis_ready: boolean;
};

export type ClipCapabilitiesT = {
  asr: {
    backend: string;
    available: boolean;
    bin?: string | null;
    model?: string | null;
    reasons: string[];
    manual_import: boolean;
    note: string;
  };
  manual_transcript: boolean;
  aspects: string[];
  presets: Record<string, { label: string; aspect: string }>;
  crop_modes: { id: string; label: string }[];
  durations: number[];
  diagnostics: { ffmpeg: string; ffprobe_standalone: boolean; note: string };
};

export type ClipProjectDetailT = {
  project: ClipProjectT;
  transcript: any | null;
  analysis: { silence_gaps: number; scene_cuts: number; envelope_windows: number; created_at?: string } | null;
  capabilities: ClipCapabilitiesT['asr'];
  jobs: ClipJobT[];
  clips: ClipCandidateT[];
  music: { name: string; path: string; url: string }[];
};

async function clipUpload(path: string, file: File) {
  const fd = new FormData();
  fd.append('file', file);
  return clipUploadForm(path, fd);
}

async function clipUploadForm(path: string, fd: FormData) {
  const r = await fetch(BASE + path, { method: 'POST', body: fd });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const t = await r.text();
      try {
        detail = JSON.parse(t).detail || t;
      } catch {
        detail = t || detail;
      }
    } catch {
      /* ignore */
    }
    throw new Error(`${r.status} ${detail}`);
  }
  return r.json();
}

export const clipApi = {
  capabilities: () => req<ClipCapabilitiesT>('/api/clip/capabilities'),
  diagnostics: () => req<any>('/api/clip/diagnostics'),
  projects: () => req<{ projects: ClipProjectT[] }>('/api/clip/projects'),
  project: (id: string) => req<ClipProjectDetailT>(`/api/clip/projects/${id}`),
  createProject: (body: { title?: string; aspect_ratio?: string; preset?: string; language?: string; prompt?: string; director_preset?: string; single_clip?: boolean; burn_captions?: boolean; transitions?: boolean }) =>
    req<{ project: ClipProjectT }>('/api/clip/projects', { method: 'POST', body: JSON.stringify(body) }),
  updateProject: (id: string, body: any) =>
    req<{ project: ClipProjectT }>(`/api/clip/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteProject: (id: string, deleteFiles = true) =>
    req(`/api/clip/projects/${id}?delete_files=${deleteFiles}`, { method: 'DELETE' }),
  uploadSource: (id: string, file: File, replace = true) =>
    clipUpload(`/api/clip/projects/${id}/source?replace_existing=${replace}`, file),
  uploadSources: (id: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append('files', f));
    return clipUploadForm(`/api/clip/projects/${id}/sources`, fd);
  },
  sources: (id: string) => req<{ sources: ClipSourceT[]; project: ClipProjectT }>(`/api/clip/projects/${id}/sources`),
  reorderSources: (id: string, sourceIds: string[]) =>
    req<{ sources: ClipSourceT[]; project: ClipProjectT }>(`/api/clip/projects/${id}/sources/order`, {
      method: 'PATCH', body: JSON.stringify({ source_ids: sourceIds }),
    }),
  deleteSource: (sid: string) =>
    req<{ ok: boolean; sources: ClipSourceT[]; project: ClipProjectT }>(`/api/clip/sources/${sid}`, { method: 'DELETE' }),
  combine: (id: string, body: { transitions?: boolean; transition_seconds?: number; target_duration?: number; aspect?: string } = {}) =>
    req<{ job: ClipJobT }>(`/api/clip/projects/${id}/combine`, { method: 'POST', body: JSON.stringify(body) }),
  sourceUrl: (id: string) => `/api/clip/projects/${id}/source/file`,
  sourceFileUrl: (sid: string) => `/api/clip/sources/${sid}/file`,
  sourceTranscript: (sid: string) => req<{ transcript: any }>(`/api/clip/sources/${sid}/transcript`),
  importSourceTranscript: (sid: string, content: string, filename = '') =>
    req<{ transcript: any }>(`/api/clip/sources/${sid}/transcript/import`, {
      method: 'POST',
      body: JSON.stringify({ content, filename }),
    }),
  transcribeSource: (sid: string) =>
    req<{ job: ClipJobT }>(`/api/clip/sources/${sid}/transcribe`, { method: 'POST' }),
  analyze: (id: string) => req<{ job: ClipJobT }>(`/api/clip/projects/${id}/analyze`, { method: 'POST' }),
  transcribe: (id: string) => req<{ job: ClipJobT }>(`/api/clip/projects/${id}/transcribe`, { method: 'POST' }),
  transcript: (id: string) => req<{ transcript: any; capability: any }>(`/api/clip/projects/${id}/transcript`),
  importTranscript: (id: string, content: string, filename = '') =>
    req<{ transcript: any }>(`/api/clip/projects/${id}/transcript/import`, {
      method: 'POST',
      body: JSON.stringify({ content, filename }),
    }),
  saveTranscript: (id: string, segments: { start: number; end: number; text: string }[]) =>
    req<{ transcript: any }>(`/api/clip/projects/${id}/transcript`, {
      method: 'PUT',
      body: JSON.stringify({ segments }),
    }),
  directorPresets: () =>
    req<{ default: string; presets: { id: string; label: string; instruction: string; default_prompt: string }[] }>(
      '/api/clip/prompt/presets',
    ),
  previewDirection: (id: string, body: { prompt: string; preset: string; single_clip?: boolean }) =>
    req<{ plan: any; brief: any; notice: string }>(
      `/api/clip/projects/${id}/direction/preview`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
  highlights: (
    id: string,
    durations: number[],
    count: number,
    prompt = '',
    opts?: { director_preset?: string; single_clip?: boolean },
  ) =>
    req<{ job: ClipJobT }>(`/api/clip/projects/${id}/highlights`, {
      method: 'POST',
      body: JSON.stringify({ durations, count, prompt, ...(opts || {}) }),
    }),
  parsePrompt: (prompt: string, preset = 'tiktok', singleClip = false) =>
    req<{ brief: any; preset: string }>('/api/clip/prompt/parse', {
      method: 'POST',
      body: JSON.stringify({ prompt, preset, single_clip: singleClip }),
    }),
  clips: (id: string) => req<{ clips: ClipCandidateT[] }>(`/api/clip/projects/${id}/clips`),
  patchClip: (cid: string, body: any) => req<{ clip: ClipCandidateT }>(`/api/clip/clips/${cid}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteClip: (cid: string) => req(`/api/clip/clips/${cid}`, { method: 'DELETE' }),
  regenerateMetadata: (cid: string) => req<{ copy: any }>(`/api/clip/clips/${cid}/metadata`, { method: 'POST' }),
  renderClip: (cid: string, body: any) => req<{ job: ClipJobT }>(`/api/clip/clips/${cid}/render`, { method: 'POST', body: JSON.stringify(body) }),
  exportBatch: (id: string, candidateIds?: string[], aspect?: string) =>
    req<{ job: ClipJobT; requested: number }>(`/api/clip/projects/${id}/export-batch`, {
      method: 'POST',
      body: JSON.stringify({ candidate_ids: candidateIds, aspect }),
    }),
  clipFileUrl: (cid: string, aspect?: string) => `/api/clip/clips/${cid}/file${aspect ? `?aspect=${aspect}` : ''}`,
  exports: (id: string) =>
    req<{ files: { name: string; size_bytes: number; url: string }[]; manifest: any }>(`/api/clip/projects/${id}/exports`),
  jobs: (id: string) => req<{ jobs: ClipJobT[] }>(`/api/clip/projects/${id}/jobs`),
  job: (jid: string) => req<{ job: ClipJobT }>(`/api/clip/jobs/${jid}`),
  cancelJob: (jid: string) => req<{ job: ClipJobT }>(`/api/clip/jobs/${jid}/cancel`, { method: 'POST' }),
};
