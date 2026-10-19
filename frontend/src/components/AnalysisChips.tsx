import { useStore } from '../store';
import { ANALYSIS_CATALOG } from '../catalog/analyses';

export default function AnalysisChips() {
  const selected = useStore((s) => s.selectedAnalysis);
  const selectAnalysis = useStore((s) => s.selectAnalysis);
  const results = useStore((s) => s.resultsByAnalysis);

  return (
    <div className="flex items-center gap-1.5 overflow-x-auto py-2 px-1" style={{ scrollbarWidth: 'thin' }}>
      {ANALYSIS_CATALOG.map((a) => {
        const isActive = a.id === selected;
        const hasResult = !!results[a.id];
        return (
          <button
            key={a.id}
            onClick={() => selectAnalysis(a.id)}
            className="flex items-center gap-1.5 px-3 h-8 rounded text-xs font-500 whitespace-nowrap transition-all"
            style={{
              fontFamily: 'var(--font-display)',
              background: isActive ? 'var(--teal-700)' : 'transparent',
              color: isActive ? 'var(--white)' : 'var(--ink-muted)',
              border: `1px solid ${isActive ? 'var(--teal-700)' : 'var(--slate-200)'}`,
              cursor: 'pointer',
            }}
          >
            {a.short}
            {hasResult && (
              <span
                className="w-1.5 h-1.5 rounded-full"
                style={{ background: isActive ? 'var(--teal-200)' : 'var(--success)' }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
