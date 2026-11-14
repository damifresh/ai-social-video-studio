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
