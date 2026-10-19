import { useStore } from '../store';
import type { WeatherFile } from '../api';

export default function WeatherSelector() {
  const weatherFiles = useStore((s) => s.weatherFiles);
  const selectedWeather = useStore((s) => s.selectedWeather);
  const selectWeather = useStore((s) => s.selectWeather);

  const selected = weatherFiles?.find((w) => w.id === selectedWeather);

  return (
    <div>
      <p className="text-xs font-500 mb-2" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>2. WEATHER FILE</p>
      {weatherFiles === null ? (
        <div className="skeleton h-10 rounded-lg" />
      ) : weatherFiles.length === 0 ? (
        <p className="text-xs" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>No weather files available</p>
      ) : (
        <>
          <select
            value={selectedWeather ?? ''}
            onChange={(e) => selectWeather(e.target.value)}
            className="w-full px-3 h-10 rounded-lg text-sm outline-none"
            style={{ fontFamily: 'var(--font-display)', border: '1px solid var(--slate-200)', background: 'var(--white)', color: 'var(--ink)' }}
          >
            {weatherFiles.map((w: WeatherFile) => (
              <option key={w.id} value={w.id}>
                {w.station_name} ({w.country}, {Math.round(w.elevation_m)}m)
              </option>
            ))}
          </select>
          {selected && (
            <div className="mt-2 p-2.5 rounded-lg text-xs space-y-1" style={{ fontFamily: 'var(--font-mono)', background: 'var(--slate-50)', color: 'var(--ink-muted)' }}>
              <div className="flex justify-between"><span>Station ID</span><span style={{ color: 'var(--ink)' }}>{selected.station_id}</span></div>
              <div className="flex justify-between"><span>Coordinates</span><span className="tabular-nums" style={{ color: 'var(--ink)' }}>{selected.latitude.toFixed(3)}, {selected.longitude.toFixed(3)}</span></div>
              <div className="flex justify-between"><span>Elevation</span><span className="tabular-nums" style={{ color: 'var(--ink)' }}>{selected.elevation_m}m</span></div>
              <div className="flex justify-between"><span>Data period</span><span style={{ color: 'var(--ink)' }}>{selected.data_period}</span></div>
              {selected.quality_score && (
                <div className="flex justify-between"><span>Vetted grade</span><span style={{ color: 'var(--ink)' }}>{selected.quality_score}</span></div>
              )}
              {selected.source === 'unvetted' && (
                <p style={{ color: 'var(--warning)' }}>Not in the vetted manifest — provenance unknown.</p>
              )}
              {selected.source === 'upload' && (
                <p style={{ color: 'var(--ink-muted)' }}>Uploaded for this project.</p>
              )}
              {selected.recommended_for && (
                <p className="pt-1" style={{ color: 'var(--ink)' }}>{selected.recommended_for}</p>
              )}
              {/* Station limitations from the manifest travel with the file into the results view. */}
              {selected.limitations?.map((limitation) => (
                <p key={limitation} className="leading-snug">— {limitation}</p>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
