import type { HistogramBin } from '../api';
import { jetCss } from '../catalog/analyses';

export default function Histogram({
  bins,
  valueRange,
  cursorValue,
}: {
  bins: HistogramBin[];
  valueRange: [number, number];
  cursorValue?: number | null;
}) {
  const maxCount = Math.max(...bins.map((b) => b.count), 1);
  const [lo, hi] = valueRange;
  const cursorPct = cursorValue != null ? ((cursorValue - lo) / (hi - lo)) * 100 : null;

  return (
    <div>
      <div className="flex items-end gap-px h-24">
        {bins.map((bin) => {
          const t = (bin.min + bin.max) / 2;
          const norm = (t - lo) / (hi - lo);
          const height = `${(bin.count / maxCount) * 100}%`;
          return (
            <div
              key={bin.index}
              className="flex-1 rounded-t-sm transition-all"
              style={{ height, background: jetCss(norm, 0.85), minHeight: '2px' }}
            />
          );
        })}
      </div>
      <div className="flex justify-between mt-1.5 text-xs" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>
        <span>{lo.toFixed(1)}</span>
        <span>{hi.toFixed(1)}</span>
      </div>
      {cursorPct != null && cursorPct >= 0 && cursorPct <= 100 && (
        <div
          className="absolute top-0 bottom-6 w-px"
          style={{ left: `${cursorPct}%`, background: 'var(--ink)', opacity: 0.5 }}
        />
      )}
    </div>
  );
}
