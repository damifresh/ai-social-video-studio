import { Routes, Route, NavLink, Link } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import NewProject from './pages/NewProject'
import ProjectView from './pages/ProjectView'
import Settings from './pages/Settings'

const nav = [
  { to: '/', label: 'Dashboard' },
  { to: '/new', label: 'New Project' },
  { to: '/settings', label: 'Settings' },
]

export default function App() {
  return (
    <div className="min-h-screen flex">
      <aside className="w-64 bg-slate-900/70 border-r border-slate-800 p-5 flex flex-col">
        <Link to="/" className="text-lg font-semibold mb-6">🎬 AI Video Studio</Link>
        <nav className="space-y-1">
          {nav.map(n => (
            <NavLink key={n.to} to={n.to} end={n.to==='/'}
              className={({isActive})=>`block px-3 py-2 rounded-lg text-sm ${isActive?'bg-indigo-600 text-white':'text-slate-300 hover:bg-slate-800'}`}>{n.label}</NavLink>
          ))}
        </nav>
        <div className="mt-auto text-xs text-slate-500">Local · 720p · No cloud APIs</div>
      </aside>
      <main className="flex-1 p-8 overflow-auto">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<NewProject />} />
          <Route path="/project/:id" element={<ProjectView />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}
