import { useEffect, useRef, useState } from 'react';
import { api, JobT } from '../lib/api';

export function useJob(jobId?: string | null, onDone?: (job: JobT) => void) {
  const [job, setJob] = useState<JobT | null>(null);
  const [error, setError] = useState('');
  const timer = useRef<any>(null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    let alive = true;
    const poll = async () => {
      try {
        const r = await api.job(jobId);
        if (!alive) return;
        setJob(r.job);
        if (['succeeded', 'failed', 'canceled', 'interrupted'].includes(r.job.status)) {
          if (timer.current) clearInterval(timer.current);
          timer.current = null;
          doneRef.current?.(r.job);
        }
      } catch (e: any) {
        if (alive) setError(String(e.message || e));
      }
    };
    poll();
    timer.current = setInterval(poll, 1200);
    return () => {
      alive = false;
      if (timer.current) clearInterval(timer.current);
      timer.current = null;
    };
  }, [jobId]);

  return { job, error, setJob };
}

export function useSystem(intervalMs = 5000) {
  const [system, setSystem] = useState<any>(null);
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const s = await api.system();
        if (alive) {
          setSystem(s);
          setOnline(true);
        }
      } catch {
        if (alive) setOnline(false);
      }
    };
    load();
    const t = setInterval(load, intervalMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [intervalMs]);

  return { system, online };
}
