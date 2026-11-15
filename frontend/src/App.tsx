import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import NewProject from './pages/NewProject';
import ProjectView from './pages/ProjectView';
import Library from './pages/Library';
import Exports from './pages/Exports';
import Benchmark from './pages/Benchmark';
import ClipStudio from './pages/ClipStudio';
import ClipProject from './pages/ClipProject';
import Settings from './pages/Settings';

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/new" element={<NewProject />} />
        <Route path="/project/:id" element={<ProjectView />} />
        <Route path="/clip" element={<ClipStudio />} />
        <Route path="/clip/:id" element={<ClipProject />} />
        <Route path="/library" element={<Library />} />
        <Route path="/exports" element={<Exports />} />
        <Route path="/benchmark" element={<Benchmark />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
