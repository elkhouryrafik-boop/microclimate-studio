import { Routes, Route, Navigate } from 'react-router-dom';
import Header from './components/Header';
import ProjectsPage from './components/ProjectsPage';
import ProjectWorkspace from './components/ProjectWorkspace';

export default function App() {
  return (
    <div className="min-h-screen flex flex-col" style={{ background: 'var(--background)', color: 'var(--foreground)' }}>
      <Header />
      <main className="flex-1 flex flex-col">
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/project/:id" element={<ProjectWorkspace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
