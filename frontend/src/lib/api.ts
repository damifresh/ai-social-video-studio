const BASE = '';

async function req(path: string, init?: RequestInit) {
  const r = await fetch(BASE + path, { headers: { 'Content-Type': 'application/json', ...(init?.headers||{}) }, ...init });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  const ct = r.headers.get('content-type') || '';
  if (ct.includes('application/json')) return r.json();
  return r.text();
}

export const api = {
  health: () => req('/health'),
  voices: () => req('/api/voices'),
  projects: () => req('/api/projects'),
  project: (id: string) => req(`/api/projects/${id}`),
  createProject: (body: any) => req('/api/projects', { method: 'POST', body: JSON.stringify(body) }),
  updateProject: (id: string, body: any) => req(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteProject: (id: string) => req(`/api/projects/${id}`, { method: 'DELETE' }),
  duplicateProject: (id: string) => req(`/api/projects/${id}/duplicate`, { method: 'POST' }),
  generateScript: (id: string) => req(`/api/projects/${id}/generate-script`, { method: 'POST' }),
  saveScript: (id: string, body: any) => req(`/api/projects/${id}/script`, { method: 'PUT', body: JSON.stringify(body) }),
  saveScenes: (id: string, body: any) => req(`/api/projects/${id}/scenes`, { method: 'PUT', body: JSON.stringify(body) }),
  generate: (id: string) => req(`/api/projects/${id}/generate`, { method: 'POST' }),
  regenScene: (id: string, idx: number) => req(`/api/projects/${id}/scenes/${idx}/regenerate`, { method: 'POST' }),
  job: (id: string) => req(`/api/jobs/${id}`),
  projectJobs: (id: string) => req(`/api/projects/${id}/jobs`),
  fileUrl: (pid: string, kind: string) => `/api/projects/${pid}/files/${kind}`,
};
