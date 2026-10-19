/**
 * Microclimate Studio — API client.
 *
 * Base URL: http://localhost:8000 (FastAPI backend).
 *
 * Every endpoint degrades gracefully: when the backend is unreachable the
 * client falls back to deterministic mock data so the full workflow stays
 * explorable end-to-end. `mock: true` on the result signals demo mode to the UI.
 *
 * Expected backend contracts (the FastAPI app is built against these shapes):
 *   GET  /projects                      -> Project[]
 *   POST /projects            {name}    -> Project
 *   POST /projects/:id/upload (multipart)-> UploadResponse
 *   GET  /projects/:id/weather          -> WeatherFile[]
 *   POST /projects/:id/run    (RunPayload)-> Results
 *   GET  /projects/:id/results          -> Results | null
 */

import { getAnalysis, jetColor, windowHours, type ParamValue } from './catalog/analyses';

const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export interface Project {
  id: string;
  name: string;
  location: string;
  description: string;
  createdAt: string;
  updatedAt: string;
  analysisCount: number;
  lastRunAt: string | null;
  latitude: number;
  longitude: number;
}

export interface WeatherFile {
  id: string;
  filename: string;
  station_name: string;
  station_id: string;
  country: string;
  latitude: number;
  longitude: number;
  elevation_m: number;
  timezone_utc_offset: number;
  data_type: string;
  data_period: string;
  /** Provenance from the vetted library manifest — absent on uploads. */
  source?: 'library' | 'unvetted' | 'upload';
  quality_score?: string;
  recommended_for?: string;
  limitations?: string[];
}

/** A single extruded building footprint, in [longitude, latitude] degrees. */
export interface BuildingPart {
  polygon: [number, number][];
  height: number; // meters
}

export interface KpiValue {
  key: string;
  label: string;
  value: number;
  unit: string;
}

export interface HistogramBin {
  index: number;
  min: number;
  max: number;
  count: number;
}

export interface HeatmapData {
  imageUrl: string;
  bounds: [[number, number], [number, number]]; // [[west, south], [east, north]]
}

export interface ResultsMetadata {
  station: string;
  latitude: number;
  longitude: number;
  analysis: string;
  analysis_label: string;
  weather_file: string;
  model: string;
  timestamp: string;
  duration_s: number;
}

export interface Results {
  analysis: string;
  /** "fake" = synthetic engine (not physics); "infrared" = real SDK run. */
  engine?: 'fake' | 'infrared';
  unit: string;
  valueRange: [number, number];
  kpis: KpiValue[];
  histogram: HistogramBin[];
  metadata: ResultsMetadata;
  heatmap: HeatmapData | null;
  /** Sparse value grid for the contour overlay (colour-blind cue). */
  contourPoints: { position: [number, number]; value: number }[] | null;
  contourBounds: [[number, number], [number, number]] | null;
}

export interface RunPayload {
  analysis: string;
  weather_id: string | null;
  model_name: string;
  /** Real SDK fields — numbers for sliders, kebab-case enum values for selects. */
  params: Record<string, ParamValue>;
  /** Optional site centre — the backend falls back to the project's own. */
  latitude?: number;
  longitude?: number;
}

export interface ModelStats {
  buildings: number;
  elements: number;
  triangles: number;
  footprint_parts: number;
  site_width_m: number;
  site_height_m: number;
  model_height_m: number;
  schema: string;
}

export interface UploadResponse {
  status: string;
  model_name: string;
  building: BuildingPart[] | null;
  /** Site polygon derived from the building extent, in [lon, lat]. */
  polygon?: GeoPolygon;
  /** Site centre — replaces the project's if the IFC is georeferenced. */
  latitude?: number;
  longitude?: number;
  stats?: ModelStats;
  warnings?: string[];
  message?: string | null;
}

export interface GeoPolygon {
  type: 'Polygon';
  coordinates: [number, number][][];
}

export interface ApiResult<T> {
  data: T;
  mock: boolean;
}

/** Real backend error (HTTP 4xx/5xx) — surfaced to the user, no fallback. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Backend unreachable — triggers the mock fallback path. */
class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NetworkError';
  }
}

async function http<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
  timeoutMs = 8000,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers = new Headers(init.headers);
  let body: BodyInit | undefined;
  if (init.json !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(init.json);
  } else if (init.body) {
    body = init.body as BodyInit;
  }
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      body,
      signal: controller.signal,
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      throw new ApiError(res.status, detail || `Request failed (${res.status})`);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    const reason = err instanceof Error ? err.message : String(err);
    throw new NetworkError(`${path} — ${reason}`);
  } finally {
    clearTimeout(timer);
  }
}

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export const api = {
  async listProjects(): Promise<ApiResult<Project[]>> {
    try {
      return { data: await http<Project[]>('/projects'), mock: false };
    } catch (err) {
      if (err instanceof NetworkError) {
        console.warn('[api] GET /projects unavailable — using demo data.', err.message);
        return { data: mockProjects(), mock: true };
      }
      throw err;
    }
  },

  async createProject(name: string): Promise<ApiResult<Project>> {
    try {
      return { data: await http<Project>('/projects', { method: 'POST', json: { name } }), mock: false };
    } catch (err) {
      if (err instanceof NetworkError) {
        console.warn('[api] POST /projects unavailable — using demo data.', err.message);
        await delay(350);
        return { data: mockCreateProject(name), mock: true };
      }
      throw err;
    }
  },

  async uploadModel(projectId: string, file: File): Promise<ApiResult<UploadResponse>> {
    const fd = new FormData();
    fd.append('file', file);
    try {
      return {
        data: await http<UploadResponse>(`/projects/${projectId}/upload`, { method: 'POST', body: fd }, 30000),
        mock: false,
      };
    } catch (err) {
      if (err instanceof NetworkError) {
        console.warn('[api] POST /upload unavailable — using demo geometry.', err.message);
        await delay(900);
        return { data: mockUpload(file), mock: true };
      }
      throw err;
    }
  },

  async listWeather(projectId: string): Promise<ApiResult<WeatherFile[]>> {
    try {
      return { data: await http<WeatherFile[]>(`/projects/${projectId}/weather`), mock: false };
    } catch (err) {
      if (err instanceof NetworkError) {
        console.warn('[api] GET /weather unavailable — using demo weather library.', err.message);
        return { data: mockWeatherFiles(), mock: true };
      }
      throw err;
    }
  },

  async uploadWeather(projectId: string, file: File): Promise<ApiResult<WeatherFile>> {
    const fd = new FormData();
    fd.append('file', file);
    try {
      return {
        data: await http<WeatherFile>(`/projects/${projectId}/weather`, { method: 'POST', body: fd }, 30000),
        mock: false,
      };
    } catch (err) {
      if (err instanceof NetworkError) {
        console.warn('[api] POST /weather unavailable — parsing the EPW header locally.', err.message);
        return { data: await localEpwFile(file), mock: true };
      }
      throw err;
    }
  },

  async runAnalysis(projectId: string, payload: RunPayload): Promise<ApiResult<Results>> {
    try {
      return {
        data: await http<Results>(`/projects/${projectId}/run`, { method: 'POST', json: payload }, 120000),
        mock: false,
      };
    } catch (err) {
      if (err instanceof NetworkError) {
        console.warn('[api] POST /run unavailable — synthesising demo results.', err.message);
        await delay(1400);
        return { data: mockResults(payload), mock: true };
      }
      throw err;
    }
  },

  async fetchResults(projectId: string): Promise<ApiResult<Results | null>> {
    try {
      return { data: await http<Results | null>(`/projects/${projectId}/results`), mock: false };
    } catch (err) {
      if (err instanceof NetworkError) {
        console.warn('[api] GET /results unavailable — no cached results.', err.message);
        return { data: null, mock: true };
      }
      throw err;
    }
  },
};

/* ---------------------------------------------------------------------------
 * Mock fallbacks — deterministic per project/weather/params so results feel
 * stable and believable while the backend is unreachable.
 * ------------------------------------------------------------------------- */

export function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function mockProjects(): Project[] {
  return [
    {
      id: 'prj-tower',
      name: 'Synthetic tower block',
      location: 'Synthetic sample site',
      description: 'Residential tower — wind & thermal comfort study (demo data)',
      createdAt: '2026-07-18T09:30:00Z',
      updatedAt: '2026-08-01T14:05:00Z',
      analysisCount: 4,
      lastRunAt: '2026-08-01T14:05:00Z',
      latitude: 10.0,
      longitude: 20.0,
    },
    {
      id: 'prj-demo',
      name: 'Demo Villa',
      location: 'Synthetic sample site',
      description: 'Low-rise house — daylight & solar radiation (demo data)',
      createdAt: '2026-07-25T11:00:00Z',
      updatedAt: '2026-07-28T10:12:00Z',
      analysisCount: 2,
      lastRunAt: '2026-07-28T10:12:00Z',
      latitude: 10.0,
      longitude: 20.0,
    },
    {
      id: 'prj-block',
      name: 'Demo mixed-use block',
      location: 'Synthetic sample site',
      description: 'Mixed-use block — pedestrian wind comfort (demo data)',
      createdAt: '2026-06-02T08:00:00Z',
      updatedAt: '2026-07-15T16:40:00Z',
      analysisCount: 0,
      lastRunAt: null,
      latitude: 10.0,
      longitude: 20.0,
    },
  ];
}

export function mockCreateProject(name: string): Project {
  return {
    id: `prj-${Date.now().toString(36)}${Math.floor(Math.random() * 36).toString(36)}`,
    name,
    location: 'Synthetic sample site',
    description: '',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    analysisCount: 0,
    lastRunAt: null,
    latitude: 10.0,
    longitude: 20.0,
  };
}

export function mockWeatherFiles(): WeatherFile[] {
  const station = (k: string, i: number, elev: number): WeatherFile => ({
    id: `station_${k}`,
    filename: `station_${k}.epw`,
    station_name: `Reference station ${k.toUpperCase()}`,
    station_id: String(i + 1).padStart(6, '0'),
    country: 'n/a',
    latitude: 10.0,
    longitude: 20.0,
    elevation_m: elev,
    timezone_utc_offset: 0,
    data_type: 'TMYx',
    data_period: '2007–2021',
  });
  return [
    station('a', 0, 26.5),
    station('b', 1, 1524),
    station('c', 2, 920),
    station('d', 3, 10.4),
    station('e', 4, 26.8),
  ];
}

export function mockUpload(file: File): UploadResponse {
  return {
    status: 'ok',
    model_name: file.name,
    building: null,
    message: 'Demo parse — geometry generated locally.',
  };
}

/**
 * Demo-mode EPW ingest: read the LOCATION header client-side so an uploaded
 * file still shows real station metadata while the backend is unreachable.
 */
export function localEpwFile(file: File): Promise<WeatherFile> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    const fallback: WeatherFile = {
      id: `custom-${Date.now()}`,
      filename: file.name,
      station_name: file.name.replace(/\.epw$/i, ''),
      station_id: 'custom',
      country: '',
      latitude: 0,
      longitude: 0,
      elevation_m: 0,
      timezone_utc_offset: 0,
      data_type: 'EPW',
      data_period: 'uploaded',
      source: 'upload',
    };
    reader.onload = () => {
      const text = String(reader.result ?? '').slice(0, 4000);
      const line = text.split(/\r?\n/).find((l) => l.startsWith('LOCATION'));
      if (!line) {
        resolve(fallback);
        return;
      }
      const f = line.split(',');
      const num = (v: string | undefined) => {
        const n = parseFloat(v ?? '');
        return Number.isFinite(n) ? n : 0;
      };
      resolve({
        ...fallback,
        station_name: f[1]?.trim() || fallback.station_name,
        country: f[3]?.trim() || '',
        station_id: f[5]?.trim() || 'custom',
        latitude: num(f[6]),
        longitude: num(f[7]),
        timezone_utc_offset: num(f[8]),
        elevation_m: num(f[9]),
      });
    };
    reader.onerror = () => resolve(fallback);
    reader.readAsText(file);
  });
}

/** Deterministic pseudo-building: L-shaped tower + slab + podium. */
export function mockBuilding(project: Project): BuildingPart[] {
  const rng = mulberry32(hashStr(`${project.id}:site`));
  const latM = 1 / 111320;
  const lonM = 1 / (111320 * Math.max(0.2, Math.cos((project.latitude * Math.PI) / 180)));
  const ox = (rng() - 0.5) * 0.0012;
  const oy = (rng() - 0.5) * 0.0012;
  const toLon = (mx: number) => project.longitude + ox + mx * lonM;
  const toLat = (my: number) => project.latitude + oy + my * latM;

  const towerH = 38 + rng() * 14;
  const slabH = 11 + rng() * 4;
  const podiumH = 4.5;

  const tower: [number, number][] = [
    [0, 0], [22, 0], [22, 12], [13, 12], [13, 20], [0, 20],
  ].map(([x, y]) => [toLon(x), toLat(y)]);
  const slab: [number, number][] = [
    [30, -9], [56, -9], [56, 5], [30, 5],
  ].map(([x, y]) => [toLon(x), toLat(y)]);
  const podium: [number, number][] = [
    [-8, -8], [34, -8], [34, 26], [-8, 26],
  ].map(([x, y]) => [toLon(x), toLat(y)]);

  return [
    { polygon: tower, height: towerH },
    { polygon: slab, height: slabH },
    { polygon: podium, height: podiumH },
  ];
}

const SITE_RADIUS_LON = 0.0021; // ~190 m at mid latitude
const SITE_RADIUS_LAT = 0.0018;

function field01(x: number, y: number, seed: number): number {
  const n =
    Math.sin(x * 3.1 + seed) * Math.cos(y * 2.7 + seed * 0.71) +
    Math.sin((x + y) * 1.33 + seed * 1.37) * 0.55 +
    Math.cos(x * 5.3 - y * 2.1 + seed * 0.31) * 0.33;
  return Math.min(1, Math.max(0, (n + 2.1) / 4.2));
}

export function mockResults(payload: RunPayload): Results {
  const def = getAnalysis(payload.analysis);
  const seed = hashStr(
    `${payload.analysis}|${payload.weather_id}|${payload.model_name}|${JSON.stringify(payload.params)}`,
  );
  const rng = mulberry32(seed);
  const [lo, hi] = def.valueRange;
  const lat = payload.latitude ?? 10.0;
  const lon = payload.longitude ?? 20.0;
  const minLon = lon - SITE_RADIUS_LON;
  const maxLon = lon + SITE_RADIUS_LON;
  const minLat = lat - SITE_RADIUS_LAT;
  const maxLat = lat + SITE_RADIUS_LAT;

  const kpis = def.kpis.map((k) => ({ ...k, value: kpiValue(def.id, k.key, payload.params, rng) }));

  const peak = 0.22 + rng() * 0.34;
  const sigma = 0.14 + rng() * 0.12;
  const histogram = Array.from({ length: 20 }, (_, i) => {
    const t = (i + 0.5) / 20;
    const base = 340 * Math.exp(-((t - peak) ** 2) / (2 * sigma * sigma));
    const count = Math.max(0, Math.round(base * (0.7 + rng() * 0.6)));
    return {
      index: i,
      min: +(lo + (i / 20) * (hi - lo)).toFixed(3),
      max: +(lo + ((i + 1) / 20) * (hi - lo)).toFixed(3),
      count,
    };
  });

  // Dense field for the heatmap bitmap + sparse grid for contour lines.
  const N = 96;
  const cells: number[][] = [];
  const contourPoints: { position: [number, number]; value: number }[] = [];
  for (let j = 0; j < N; j++) {
    cells[j] = [];
    for (let i = 0; i < N; i++) {
      const fx = i / (N - 1);
      const fy = j / (N - 1);
      const value = +(lo + field01(fx * 4.2, fy * 4.2, seed) * (hi - lo)).toFixed(3);
      const x = minLon + fx * (maxLon - minLon);
      const y = minLat + fy * (maxLat - minLat);
      cells[j][i] = value;
      if (i % 3 === 0 && j % 3 === 0) contourPoints.push({ position: [x, y], value });
    }
  }
  const bounds: [[number, number], [number, number]] = [
    [minLon, minLat],
    [maxLon, maxLat],
  ];
  const heatmap = buildHeatmap(cells, lo, hi, 160, bounds);

  const station = mockWeatherFiles().find((w) => w.id === payload.weather_id) ?? mockWeatherFiles()[0];

  return {
    analysis: payload.analysis,
    engine: 'fake',
    unit: def.unit,
    valueRange: def.valueRange,
    kpis,
    histogram,
    metadata: {
      station: station.station_name,
      latitude: station.latitude,
      longitude: station.longitude,
      analysis: def.id,
      analysis_label: def.label,
      weather_file: station.filename,
      model: payload.model_name,
      timestamp: new Date().toISOString(),
      duration_s: +(2.4 + rng() * 5.1).toFixed(1),
    },
    heatmap,
    contourPoints,
    contourBounds: bounds,
  };
}

function buildHeatmap(
  cells: number[][],
  lo: number,
  hi: number,
  size: number,
  bounds: [[number, number], [number, number]],
): { imageUrl: string; bounds: [[number, number], [number, number]] } | null {
  const n = cells.length;
  if (n === 0) return null;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const img = ctx.createImageData(size, size);
  const span = hi - lo || 1;
  for (let j = 0; j < size; j++) {
    for (let i = 0; i < size; i++) {
      const fx = (i / size) * (n - 1);
      const fy = (j / size) * (n - 1);
      const x0 = Math.floor(fx);
      const y0 = Math.floor(fy);
      const x1 = Math.min(n - 1, x0 + 1);
      const y1 = Math.min(n - 1, y0 + 1);
      const tx = fx - x0;
      const ty = fy - y0;
      const v =
        cells[y0][x0] * (1 - tx) * (1 - ty) +
        cells[y0][x1] * tx * (1 - ty) +
        cells[y1][x0] * (1 - tx) * ty +
        cells[y1][x1] * tx * ty;
      const t = Math.min(1, Math.max(0, (v - lo) / span));
      const [r, g, b] = jetColor(t);
      const idx = (j * size + i) * 4;
      img.data[idx] = r;
      img.data[idx + 1] = g;
      img.data[idx + 2] = b;
      img.data[idx + 3] = 205;
    }
  }
  ctx.putImageData(img, 0, 0);
  return { imageUrl: canvas.toDataURL('image/png'), bounds };
}

/**
 * Demo KPI values. They react to the real parameters — moving the reference
 * wind speed or widening the window changes the numbers — so demo mode
 * exercises the controls.
 */
function kpiValue(analysis: string, key: string, p: Record<string, ParamValue>, rng: () => number): number {
  const r = () => rng();
  const num = (k: string, fallback: number) => {
    const v = Number(p[k]);
    return Number.isFinite(v) ? v : fallback;
  };
  const hours = windowHours(p) || 1;
  const days = Math.max(1, num('end_day', 28) - num('start_day', 1) + 1);

  switch (analysis) {
    case 'wind-speed': {
      // Pedestrian level sits well below the reference height, so mean site
      // speed lands around a third of the free-stream value.
      const reference = num('wind_speed', 5);
      const mean = Math.max(0.2, reference * (0.3 + r() * 0.12));
      if (key === 'mean_speed') return +mean.toFixed(2);
      if (key === 'max_speed') return +(mean * (1.6 + r() * 0.6)).toFixed(2);
      return +Math.min(100, Math.max(0, (mean / 5) * 45 + r() * 10)).toFixed(1);
    }
    case 'pedestrian-wind-comfort': {
      const strict = String(p.criteria ?? '').includes('safety') ? 0.6 : 1;
      const comfortable = Math.min(99, Math.max(20, (62 + r() * 25) * strict));
      if (key === 'comfortable_pct') return +comfortable.toFixed(1);
      if (key === 'worst_class') return Math.round(2 + r() * 2);
      return +(0.6 + (1 - comfortable / 100) * 3).toFixed(2);
    }
    case 'daylight-availability': {
      const mean = hours * (0.45 + r() * 0.25);
      if (key === 'mean_hours') return +mean.toFixed(1);
      if (key === 'max_hours') return +Math.min(hours, mean * (1.4 + r() * 0.3)).toFixed(1);
      return +Math.min(70, Math.max(3, 24 + r() * 18)).toFixed(1);
    }
    case 'direct-sun-hours': {
      const mean = hours * (0.35 + r() * 0.25);
      if (key === 'mean_hours') return +mean.toFixed(1);
      if (key === 'hours_per_day') return +(mean / days).toFixed(2);
      return +Math.min(75, Math.max(4, 28 + r() * 20)).toFixed(1);
    }
    case 'sky-view-factors': {
      const svf = 42 + r() * 30;
      if (key === 'mean_svf') return +svf.toFixed(1);
      if (key === 'min_svf') return +Math.max(2, svf - 30 - r() * 12).toFixed(1);
      return +Math.min(95, svf + r() * 15).toFixed(1);
    }
    case 'solar-radiation': {
      // Roughly 0.6 kWh/m² per sunlit hour on an unobstructed surface.
      const mean = hours * 0.6 * (0.55 + r() * 0.25);
      if (key === 'mean_irrad') return +mean.toFixed(1);
      if (key === 'max_irrad') return +(mean * (1.5 + r() * 0.4)).toFixed(1);
      return +Math.min(70, Math.max(5, 22 + r() * 18)).toFixed(1);
    }
    case 'thermal-comfort-index': {
      const month = num('month', 8);
      const summer = 1 - Math.abs(month - 7.5) / 6;
      const mean = 14 + summer * 18 + r() * 4;
      if (key === 'mean_utci') return +mean.toFixed(1);
      if (key === 'max_utci') return +(mean + 5 + r() * 5).toFixed(1);
      return +Math.min(98, Math.max(4, 100 - Math.abs(mean - 17.5) * 5.5 - r() * 8)).toFixed(1);
    }
    case 'thermal-comfort-statistics': {
      const heat = String(p.subtype ?? '') === 'heat-stress';
      const mean = hours * (heat ? 0.32 + r() * 0.25 : 0.12 + r() * 0.2);
      if (key === 'mean_hours') return +mean.toFixed(1);
      if (key === 'max_hours') return +Math.min(hours, mean * (1.5 + r() * 0.4)).toFixed(1);
      return +Math.min(95, Math.max(2, (mean / hours) * 130 + r() * 10)).toFixed(1);
    }
    default:
      return +(r() * 10).toFixed(2);
  }
}
