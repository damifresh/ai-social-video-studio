import { ReactNode } from 'react';

export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`panel ${className}`}>{children}</div>;
}

export function Button({
  children,
  onClick,
  variant = 'ghost',
  disabled,
  className = '',
  title,
  type = 'button',
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: 'primary' | 'ghost' | 'danger' | 'subtle';
  disabled?: boolean;
  className?: string;
  title?: string;
  type?: 'button' | 'submit';
}) {
  const styles: Record<string, string> = {
    primary: 'bg-gradient-to-b from-indigo-500 to-indigo-600 hover:from-indigo-400 hover:to-indigo-500 text-white shadow-lg shadow-indigo-950/40 border border-indigo-400/30',
    ghost: 'bg-white/[0.04] hover:bg-white/[0.09] text-slate-200 border border-white/10',
    subtle: 'bg-transparent hover:bg-white/[0.06] text-slate-300 border border-transparent',
    danger: 'bg-rose-600/20 hover:bg-rose-600/30 text-rose-200 border border-rose-500/30',
  };
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${styles[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

export function Badge({ children, tone = 'slate' }: { children: ReactNode; tone?: 'slate' | 'green' | 'amber' | 'red' | 'indigo' | 'violet' }) {
  const tones: Record<string, string> = {
    slate: 'bg-white/[0.06] text-slate-300 border-white/10',
    green: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
    amber: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
    red: 'bg-rose-500/10 text-rose-300 border-rose-500/20',
    indigo: 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20',
    violet: 'bg-violet-500/10 text-violet-300 border-violet-500/20',
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium tracking-wide ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function statusTone(status: string): 'slate' | 'green' | 'amber' | 'red' | 'indigo' | 'violet' {
  if (status === 'completed' || status === 'succeeded') return 'green';
  if (status === 'failed' || status === 'canceled') return 'red';
  if (status === 'generating' || status === 'running' || status === 'queued') return 'amber';
  if (status === 'interrupted') return 'violet';
  return 'slate';
}

export function Progress({ value, className = '' }: { value: number; className?: string }) {
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-white/[0.07] ${className}`}>
      <div
        className="h-full rounded-full bg-gradient-to-r from-indigo-500 via-violet-500 to-fuchsia-500 transition-all duration-500"
        style={{ width: `${Math.max(0, Math.min(100, value || 0))}%` }}
      />
    </div>
  );
}

export function Field({ label, hint, children, className = '' }: { label: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1.5 block text-[13px] font-medium text-slate-300">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] leading-relaxed text-slate-500">{hint}</span>}
    </label>
  );
}

export function Alert({ children, tone = 'red' }: { children: ReactNode; tone?: 'red' | 'amber' | 'green' | 'indigo' }) {
  const tones: Record<string, string> = {
    red: 'border-rose-500/30 bg-rose-500/10 text-rose-200',
    amber: 'border-amber-500/30 bg-amber-500/10 text-amber-100',
    green: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100',
    indigo: 'border-indigo-500/30 bg-indigo-500/10 text-indigo-100',
  };
  return <div className={`whitespace-pre-wrap rounded-xl border px-3.5 py-2.5 text-sm ${tones[tone]}`}>{children}</div>;
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 px-6 py-14 text-center">
      <div className="mb-2 text-2xl">✦</div>
      <div className="font-medium text-slate-200">{title}</div>
      {hint && <div className="mt-1 max-w-md text-sm text-slate-500">{hint}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Spinner({ className = '' }: { className?: string }) {
  return (
    <span
      className={`inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/20 border-t-white/80 ${className}`}
    />
  );
}

export function SectionTitle({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <div>
        <h2 className="text-[17px] font-semibold tracking-tight text-slate-100">{title}</h2>
        {subtitle && <p className="mt-0.5 text-[13px] text-slate-500">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}
