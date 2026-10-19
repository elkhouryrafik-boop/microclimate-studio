import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../store';
import { formatDate } from '../format';
import { IconPlus } from './icons';
import EmptyState from './EmptyState';

export default function ProjectsPage() {
  const navigate = useNavigate();
  const projects = useStore((s) => s.projects);
  const loadProjects = useStore((s) => s.loadProjects);
  const createProject = useStore((s) => s.createProject);
  const openProject = useStore((s) => s.openProject);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');

  useEffect(() => { loadProjects(); }, [loadProjects]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(false);
    const p = await createProject(newName.trim());
    setNewName('');
    if (p) {
      await openProject(p.id);
      navigate(`/project/${p.id}`);
    }
  };

  const handleOpen = async (id: string) => {
    await openProject(id);
    navigate(`/project/${id}`);
  };

  return (
    <div className="flex-1 overflow-auto" style={{ padding: '48px 48px 96px' }}>
      <div className="max-w-[1200px] mx-auto">
        <div className="flex items-end justify-between mb-12">
          <div>
            <h1 className="font-display font-900" style={{ fontFamily: 'var(--font-display)', fontSize: 'var(--text-h1)', lineHeight: 1.05, letterSpacing: '-0.015em', color: 'var(--ink)' }}>
              Climate Projects
            </h1>
            <p className="mt-2 text-sm" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>
              Infrared SDK microclimate analysis
            </p>
          </div>
          <button
            onClick={() => setCreating(true)}
            className="flex items-center gap-2 px-4 h-9 rounded text-sm font-500 transition-all"
            style={{ fontFamily: 'var(--font-display)', background: 'var(--teal-700)', color: 'var(--white)', border: 'none', cursor: 'pointer' }}
          >
            <IconPlus size={16} />
            New Project
          </button>
        </div>

        {creating && (
          <div className="mb-6 p-4 rounded-lg" style={{ background: 'var(--slate-50)', border: '1px solid var(--slate-200)' }}>
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              placeholder="Project name (e.g. Demo Villa)"
              className="w-full px-3 h-10 rounded text-sm outline-none"
              style={{ fontFamily: 'var(--font-display)', border: '1px solid var(--slate-200)', background: 'var(--white)', color: 'var(--ink)' }}
            />
            <div className="flex gap-2 mt-3">
              <button onClick={handleCreate} className="px-4 h-8 rounded text-sm" style={{ background: 'var(--teal-700)', color: 'var(--white)', border: 'none', cursor: 'pointer', fontFamily: 'var(--font-display)' }}>
                Create
              </button>
              <button onClick={() => setCreating(false)} className="px-4 h-8 rounded text-sm" style={{ background: 'transparent', color: 'var(--ink-muted)', border: 'none', cursor: 'pointer', fontFamily: 'var(--font-display)' }}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {projects === null ? (
          <div className="grid grid-cols-3 gap-4">
            {[0,1,2].map(i => (
              <div key={i} className="h-32 rounded-lg skeleton" />
            ))}
          </div>
        ) : projects.length === 0 ? (
          <div className="h-[400px]">
            <EmptyState title="No projects yet" subtitle="Create your first climate project to begin" icon="contour" />
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-4">
            {projects.map((p) => (
              <button
                key={p.id}
                onClick={() => handleOpen(p.id)}
                className="text-left p-5 rounded-lg transition-all hover:shadow-md"
                style={{ background: 'var(--white)', border: '1px solid var(--slate-200)', cursor: 'pointer', fontFamily: 'var(--font-display)' }}
              >
                <h3 className="font-700 text-base mb-1" style={{ color: 'var(--ink)' }}>{p.name}</h3>
                <p className="text-xs mb-3" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>{p.location}</p>
                <div className="flex items-center gap-3 text-xs" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>
                  <span>{p.analysisCount} analyses</span>
                  <span>·</span>
                  <span>{p.lastRunAt ? formatDate(p.lastRunAt) : 'No runs yet'}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
