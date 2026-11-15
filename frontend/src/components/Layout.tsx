import { NavLink, Link, useLocation } from 'react-router-dom';
import { ReactNode } from 'react';
import { useSystem } from '../lib/hooks';

const NAV = [
  { to: '/', label: 'Dashboard', icon: 'M3 12l9-9 9 9M5 10v10h5v-6h4v6h5V10' },
  { to: '/new', label: 'New Project', icon: 'M12 5v14M5 12h14' },
  { to: '/clip', label: 'Auto-Clip Studio', icon: 'M4 6h16M4 12h10M4 18h7M17 12l4 4-4 4' },
  { to: '/library', label: 'Asset Library', icon: 'M4 5h16v14H4zM4 9h16M9 5v14' },
  { to: '/exports', label: 'Export Center', icon: 'M12 3v12m0 0l-4-4m4 4l4-4M4 21h16' },
  { to: '/benchmark', label: 'M2 Benchmark', icon: 'M4 19h16M7 16V9m5 7V5m5 11v-4' },
  { to: '/settings', label: 'Settings', icon: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19 12a7 7 0 00-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 00-1.7-1L14.5 3h-4l-.4 2.1a7 7 0 00-1.7 1l-2.3-1-2 3.4L6 10a7 7 0 000 2l-2 1.5 2 3.4 2.3-1a7 7 0 001.7 1l.4 2.1h4l.4-2.1a7 7 0 001.7-1l2.3 1 2-3.4L19 13a7 7 0 000-1z' },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { system, online } = useSystem();
  const location = useLocation();
  const mem = system?.memory;
  const memTone = !mem ? 'text-slate-500' : mem.percent > 85 ? 'text-rose-300' : mem.percent > 70 ? 'text-amber-300' : 'text-emerald-300';

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col border-r border-white/[0.06] bg-slate-950/70 px-4 py-6 backdrop-blur-xl md:flex">
        <Link to="/" className="mb-7 flex items-center gap-3 px-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 via-violet-500 to-fuchsia-500 text-base shadow-lg shadow-indigo-950/50">
            ▶
          </span>
          <span>
            <span className="block text-[15px] font-semibold leading-tight text-white">AI Video Studio</span>
            <span className="block text-[11px] text-slate-500">Local · 8 GB safe</span>
          </span>
        </Link>

        <nav className="space-y-1">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-medium transition ${
                  isActive
                    ? 'bg-white/[0.07] text-white shadow-inner shadow-white/5'
                    : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-200'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <svg viewBox="0 0 24 24" className={`h-[17px] w-[17px] ${isActive ? 'text-indigo-300' : 'text-slate-500 group-hover:text-slate-300'}`} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                    <path d={n.icon} />
                  </svg>
                  {n.label}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto space-y-3">
          <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3">
            <div className="flex items-center justify-between text-[11px] text-slate-500">
              <span>Local engine</span>
              <span className={online ? 'text-emerald-400' : online === false ? 'text-rose-400' : 'text-slate-500'}>
                {online ? '● online' : online === false ? '● offline' : '…'}
              </span>
            </div>
            <div className="mt-2 text-[11px] text-slate-400">
              RAM <span className={memTone}>{mem ? `${mem.percent}%` : '—'}</span>
              <span className="text-slate-600"> · </span>
              {mem ? `${(mem.available_mb / 1024).toFixed(1)} GB free` : 'starting'}
            </div>
            <div className="mt-1 truncate text-[10px] text-slate-600">v{system?.version || '1.0.0'} · sequential jobs</div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-white/[0.06] bg-slate-950/70 px-5 py-3 backdrop-blur-xl md:hidden">
          <Link to="/" className="text-sm font-semibold">AI Video Studio</Link>
          <span className={`text-[11px] ${memTone}`}>{mem ? `RAM ${mem.percent}%` : ''}</span>
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b border-white/[0.06] px-3 py-2 md:hidden">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-lg px-3 py-1.5 text-xs ${isActive ? 'bg-white/10 text-white' : 'text-slate-400'}`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>

        <main key={location.pathname} className="min-w-0 flex-1 px-5 py-6 sm:px-8 sm:py-8">
          <div className="mx-auto w-full max-w-[1180px]">{children}</div>
        </main>
      </div>
    </div>
  );
}
