import { useStore } from '../store';
import { getAnalysis, windowHours, type AnalysisParamDef } from '../catalog/analyses';
import { formatStep } from '../format';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Month numbers and clock hours read as labels, not as bare integers. */
function displayValue(param: AnalysisParamDef, value: number): string {
  if (param.key === 'month') return MONTHS[Math.min(11, Math.max(0, value - 1))];
  if (param.unit === 'h' && (param.key === 'start_hour' || param.key === 'end_hour')) {
    return `${String(value).padStart(2, '0')}:00`;
  }
  return `${formatStep(value, param.step ?? 1)}${param.unit ? ` ${param.unit}` : ''}`;
}

export default function ParamControls() {
  const selectedAnalysis = useStore((s) => s.selectedAnalysis);
  const params = useStore((s) => s.params);
  const setParam = useStore((s) => s.setParam);
  const def = getAnalysis(selectedAnalysis);

  const hours = def.needsTimePeriod ? windowHours(params) : 0;

  return (
    <div>
      <p className="text-xs font-500 mb-2" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>3. PARAMETERS</p>
      <p className="text-sm font-600 mb-3" style={{ fontFamily: 'var(--font-display)', color: 'var(--ink)' }}>{def.label}</p>

      {def.params.length === 0 && (
        <p className="text-xs" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>
          No parameters — sky view factor is pure geometry.
        </p>
      )}

      <div className="space-y-4">
        {def.params.map((p) => {
          if (p.control === 'select') {
            return (
              <div key={p.key}>
                <label
                  className="text-xs block mb-1"
                  style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}
                  htmlFor={`param-${p.key}`}
                >
                  {p.label}
                </label>
                <select
                  id={`param-${p.key}`}
                  value={String(params[p.key] ?? p.default)}
                  onChange={(e) => setParam(p.key, e.target.value)}
                  title={p.help}
                  className="w-full h-8 px-2 rounded-lg text-xs"
                  style={{
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--ink)',
                    background: 'var(--white)',
                    border: '1px solid var(--slate-200)',
                  }}
                >
                  {(p.options ?? []).map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
            );
          }

          const value = Number(params[p.key] ?? p.default);
          return (
            <div key={p.key}>
              <div className="flex items-center justify-between mb-1">
                <label
                  className="text-xs"
                  style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}
                  htmlFor={`param-${p.key}`}
                  title={p.help}
                >
                  {p.label}
                </label>
                <span className="text-xs font-500 tabular-nums" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink)' }}>
                  {displayValue(p, value)}
                </span>
              </div>
              <input
                id={`param-${p.key}`}
                type="range"
                min={p.min}
                max={p.max}
                step={p.step}
                value={value}
                onChange={(e) => setParam(p.key, parseFloat(e.target.value))}
                className="range-input w-full"
              />
            </div>
          );
        })}
      </div>

      {def.needsTimePeriod && (
        <p className="text-xs mt-3 tabular-nums" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>
          {/* The window filters as a cascade of months x days x hours, so the
              hour count is not obvious from the sliders. */}
          Window: {hours} h ({Math.max(0, Number(params.end_day) - Number(params.start_day) + 1)} days
          {' × '}
          {Math.max(0, Number(params.end_hour) - Number(params.start_hour) + 1)} h)
        </p>
      )}
    </div>
  );
}
