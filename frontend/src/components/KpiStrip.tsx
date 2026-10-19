import type { KpiValue } from '../api';

export default function KpiStrip({ kpis }: { kpis: KpiValue[] }) {
  return (
    <div className="space-y-4">
      {kpis.map((kpi, i) => (
        <div key={kpi.key}>
          <p className="text-xs font-500 mb-0.5" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>{kpi.label}</p>
          <div className="flex items-baseline gap-1.5">
            <span
              className="font-display font-900 tabular-nums"
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: i === 0 ? 'clamp(2rem, 1.5rem + 2vw, 3rem)' : '1.75rem',
                lineHeight: 1.1,
                color: 'var(--ink)',
                letterSpacing: '-0.01em',
              }}
            >
              {kpi.value.toLocaleString('en-GB', { maximumFractionDigits: 2 })}
            </span>
            <span className="text-sm" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>{kpi.unit}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
