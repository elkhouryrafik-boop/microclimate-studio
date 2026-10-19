import { Link, useLocation } from 'react-router-dom';
import { useStore } from '../store';

export default function Header() {
  const offline = useStore((s) => s.offline);
  const location = useLocation();
  const activeProject = useStore((s) => s.activeProject);

  return (
    <header
      className="flex items-center justify-between px-6 h-14 shrink-0"
      style={{ background: 'linear-gradient(180deg, var(--slate-900) 0%, var(--slate-800) 100%)', color: 'var(--white)' }}
    >
      <Link to="/" className="flex items-center gap-3 group" style={{ textDecoration: 'none', color: 'inherit' }}>
        {/* neutral glyph */}
        <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
          <rect width="32" height="32" rx="5" fill="var(--slate-700)" />
          <circle cx="16" cy="16" r="7" stroke="var(--teal-200)" strokeWidth="1.75" fill="none" />
          <path d="M9 16h14M16 9v14" stroke="var(--teal-200)" strokeWidth="1.25" opacity="0.6" />
        </svg>
        <span className="font-display font-700 text-[15px] tracking-[-0.01em]" style={{ fontFamily: 'var(--font-display)' }}>
          Microclimate Studio
        </span>
      </Link>

      <div className="flex items-center gap-4">
        {offline && (
          <span
            className="font-mono text-[11px] px-2 py-0.5 rounded"
            style={{ fontFamily: 'var(--font-mono)', background: 'rgba(183,219,255,0.12)', color: 'var(--teal-200)' }}
          >
            DEMO DATA · SYNTHETIC
          </span>
        )}
        {location.pathname.startsWith('/project/') && activeProject && (
          <nav className="flex items-center gap-2 text-[13px]" style={{ fontFamily: 'var(--font-display)' }}>
            <Link to="/" className="opacity-60 hover:opacity-100 transition-opacity" style={{ color: 'var(--teal-200)', textDecoration: 'none' }}>
              Projects
            </Link>
            <span className="opacity-40">/</span>
            <span className="font-500">{activeProject.name}</span>
          </nav>
        )}
      </div>
    </header>
  );
}
