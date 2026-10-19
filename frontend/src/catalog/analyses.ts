/**
 * Microclimate Studio — analysis catalog.
 *
 * The 8 Infrared SDK analysis types. Every parameter here maps 1:1 onto a
 * field of an SDK request payload — move a control and the simulation changes.
 * This file mirrors `backend/catalog.py`, which is the source of truth and
 * serves the same shapes from `GET /analyses`; the local copy is what lets the
 * UI stay usable while the backend is down. Keep the two in step.
 *
 * `valueRange` is only a fallback for demo mode — a real run returns the
 * legend bounds the SDK calibrated for that analysis.
 */

export type ParamValue = number | string;

export interface AnalysisOption {
  value: string;
  label: string;
}

export interface AnalysisParamDef {
  key: string;
  label: string;
  unit: string;
  control: 'slider' | 'select';
  default: ParamValue;
  min?: number;
  max?: number;
  step?: number;
  options?: AnalysisOption[];
  help?: string;
}

export interface KpiDef {
  key: string;
  label: string;
  unit: string;
}

export interface AnalysisDef {
  id: string;
  label: string;
  short: string; // chip label
  description: string;
  unit: string;
  valueRange: [number, number];
  params: AnalysisParamDef[];
  kpis: KpiDef[];
  needsWeather: boolean;
  needsTimePeriod: boolean;
  notes?: string[];
}

/**
 * Shared TimePeriod controls. The inference layer's sun-vector generator only
 * honours one month per run, so the window is a single month: pick the month,
 * then the day and hour ranges inside it. The filter is a cascade
 * (months × days × hours), not a continuous span — 1–28 at 09:00–17:00 is
 * 252 hours, not four weeks of clock time.
 */
function timeParams(opts: {
  month: number;
  startHour: number;
  endHour: number;
  endDay?: number;
}): AnalysisParamDef[] {
  return [
    {
      key: 'month',
      label: 'Month',
      unit: '',
      control: 'slider',
      default: opts.month,
      min: 1,
      max: 12,
      step: 1,
      help: 'Single-month window — one run generates sun vectors for one month.',
    },
    { key: 'start_day', label: 'First day', unit: '', control: 'slider', default: 1, min: 1, max: 31, step: 1 },
    {
      key: 'end_day',
      label: 'Last day',
      unit: '',
      control: 'slider',
      default: opts.endDay ?? 28,
      min: 1,
      max: 31,
      step: 1,
    },
    {
      key: 'start_hour',
      label: 'First hour',
      unit: 'h',
      control: 'slider',
      default: opts.startHour,
      min: 0,
      max: 23,
      step: 1,
    },
    {
      key: 'end_hour',
      label: 'Last hour',
      unit: 'h',
      control: 'slider',
      default: opts.endHour,
      min: 0,
      max: 23,
      step: 1,
    },
  ];
}

export const ANALYSIS_CATALOG: AnalysisDef[] = [
  {
    id: 'wind-speed',
    label: 'Wind speed at pedestrian level',
    short: 'Wind Speed',
    description: 'Steady-state wind magnitude near pedestrian height for one inflow condition.',
    unit: 'm/s',
    valueRange: [0, 15],
    needsWeather: false,
    needsTimePeriod: false,
    params: [
      {
        key: 'wind_speed',
        label: 'Reference wind speed',
        unit: 'm/s',
        control: 'slider',
        default: 5,
        min: 0.5,
        max: 50,
        step: 0.5,
        help: 'Applied as a linear scalar on the inferred wind-factor field — fractional values are normal.',
      },
      {
        key: 'wind_direction',
        label: 'Wind direction',
        unit: '°',
        control: 'slider',
        default: 270,
        min: 0,
        max: 345,
        step: 15,
        help: 'Meteorological convention — 270 means wind FROM the west.',
      },
    ],
    kpis: [
      { key: 'mean_speed', label: 'Mean speed', unit: 'm/s' },
      { key: 'max_speed', label: 'Max speed', unit: 'm/s' },
      { key: 'above_5_pct', label: 'Area > 5 m/s', unit: '%' },
    ],
    notes: ['Single-direction snapshot. For a year of weather use Pedestrian Wind Comfort.'],
  },
  {
    id: 'pedestrian-wind-comfort',
    label: 'Pedestrian wind comfort',
    short: 'Ped. Comfort',
    description: 'Comfort class per cell over a weather window, using the selected standard.',
    unit: 'class',
    valueRange: [0, 4],
    needsWeather: true,
    needsTimePeriod: true,
    params: [
      {
        key: 'criteria',
        label: 'Criterion',
        unit: '',
        control: 'select',
        default: 'lawson-2001',
        options: [
          { value: 'lawson-2001', label: 'Lawson 2001' },
          { value: 'lawson-1970', label: 'Lawson 1970' },
          { value: 'lawson-lddc', label: 'Lawson LDDC' },
          { value: 'vdi-3787', label: 'VDI 3787' },
          { value: 'davenport', label: 'Davenport' },
          { value: 'nen-8100-comfort', label: 'NEN 8100 — comfort' },
          { value: 'nen-8100-safety', label: 'NEN 8100 — safety' },
        ],
        help: 'NEN 8100 safety scores storm risk, not comfort — a different question.',
      },
      ...timeParams({ month: 1, startHour: 8, endHour: 20 }),
    ],
    kpis: [
      { key: 'comfortable_pct', label: 'Comfortable area', unit: '%' },
      { key: 'worst_class', label: 'Worst class', unit: '' },
      { key: 'mean_class', label: 'Mean class', unit: '' },
    ],
  },
  {
    id: 'daylight-availability',
    label: 'Daylight availability',
    short: 'Daylight',
    description: 'Cumulative hours of usable daylight per cell over the window.',
    unit: 'h',
    valueRange: [0, 300],
    needsWeather: false,
    needsTimePeriod: true,
    params: timeParams({ month: 6, startHour: 9, endHour: 17 }),
    kpis: [
      { key: 'mean_hours', label: 'Mean daylight', unit: 'h' },
      { key: 'max_hours', label: 'Max daylight', unit: 'h' },
      { key: 'dark_pct', label: 'Area < 25% of max', unit: '%' },
    ],
  },
  {
    id: 'direct-sun-hours',
    label: 'Direct sun hours',
    short: 'Sun Hours',
    description: 'Cumulative un-occluded sun hours per cell, summed over the filtered hour set.',
    unit: 'h',
    valueRange: [0, 300],
    needsWeather: false,
    needsTimePeriod: true,
    params: timeParams({ month: 6, startHour: 9, endHour: 17 }),
    kpis: [
      { key: 'mean_hours', label: 'Mean sun hours', unit: 'h' },
      { key: 'hours_per_day', label: 'Mean per day', unit: 'h/d' },
      { key: 'shaded_pct', label: 'Area < 25% of max', unit: '%' },
    ],
    notes: ['Absolute hours depend on window length — normalise before comparing runs.'],
  },
  {
    id: 'sky-view-factors',
    label: 'Sky view factors',
    short: 'Sky View',
    description: 'Share of the upper hemisphere visible from each ground cell.',
    unit: '%',
    valueRange: [0, 100],
    needsWeather: false,
    needsTimePeriod: false,
    params: [],
    kpis: [
      { key: 'mean_svf', label: 'Mean SVF', unit: '%' },
      { key: 'min_svf', label: 'Min SVF', unit: '%' },
      { key: 'open_pct', label: 'Area > 50%', unit: '%' },
    ],
    notes: ['Pure geometry — no weather, no season. One run covers all conditions.'],
  },
  {
    id: 'solar-radiation',
    label: 'Solar radiation',
    short: 'Solar Rad.',
    description: 'Cumulative shortwave irradiance per cell over the weather window.',
    unit: 'kWh/m²',
    valueRange: [0, 400],
    needsWeather: true,
    needsTimePeriod: true,
    params: timeParams({ month: 6, startHour: 6, endHour: 20 }),
    kpis: [
      { key: 'mean_irrad', label: 'Mean irradiance', unit: 'kWh/m²' },
      { key: 'max_irrad', label: 'Max irradiance', unit: 'kWh/m²' },
      { key: 'low_pct', label: 'Area < 25% of max', unit: '%' },
    ],
  },
  {
    id: 'thermal-comfort-index',
    label: 'Thermal comfort index (UTCI)',
    short: 'UTCI',
    description: 'Universal Thermal Climate Index — outdoor felt temperature.',
    unit: '°C',
    valueRange: [-10, 50],
    needsWeather: true,
    needsTimePeriod: true,
    params: timeParams({ month: 8, startHour: 10, endHour: 18 }),
    kpis: [
      { key: 'mean_utci', label: 'Mean UTCI', unit: '°C' },
      { key: 'max_utci', label: 'Max UTCI', unit: '°C' },
      { key: 'no_stress_pct', label: 'No thermal stress', unit: '%' },
    ],
    notes: ['No thermal stress = 9–26 °C UTCI (ISB commission band).'],
  },
  {
    id: 'thermal-comfort-statistics',
    label: 'Thermal comfort statistics',
    short: 'Therm. Stats',
    description: 'Hours per cell falling in the selected comfort or stress band.',
    unit: 'h',
    valueRange: [0, 300],
    needsWeather: true,
    needsTimePeriod: true,
    params: [
      {
        key: 'subtype',
        label: 'Band',
        unit: '',
        control: 'select',
        default: 'heat-stress',
        options: [
          { value: 'thermal-comfort', label: 'Thermal comfort' },
          { value: 'heat-stress', label: 'Heat stress' },
          { value: 'cold-stress', label: 'Cold stress' },
        ],
        help: 'One band per run — each subtype is a separate simulation.',
      },
      ...timeParams({ month: 8, startHour: 8, endHour: 20 }),
    ],
    kpis: [
      { key: 'mean_hours', label: 'Mean hours in band', unit: 'h' },
      { key: 'max_hours', label: 'Max hours in band', unit: 'h' },
      { key: 'exposed_pct', label: 'Area > 50% of window', unit: '%' },
    ],
  },
];

export function getAnalysis(id: string): AnalysisDef {
  return ANALYSIS_CATALOG.find((a) => a.id === id) ?? ANALYSIS_CATALOG[0];
}

export function defaultParamsFor(id: string): Record<string, ParamValue> {
  const out: Record<string, ParamValue> = {};
  for (const p of getAnalysis(id).params) out[p.key] = p.default;
  return out;
}

/** Hours the cascade filter keeps for a window — months × days × hours. */
export function windowHours(params: Record<string, ParamValue>): number {
  const num = (key: string) => Number(params[key] ?? 0);
  const days = Math.max(0, num('end_day') - num('start_day') + 1);
  const hours = Math.max(0, num('end_hour') - num('start_hour') + 1);
  return days * hours;
}

/* ---------------------------------------------------------------------------
 * Jet scale — shared by the heatmap bitmap and the histogram bars.
 * Identical to the ramp `backend/results.py` renders the PNG with, so the map
 * and the chart agree cell for cell.
 * ------------------------------------------------------------------------- */

const JET_STOPS: Array<[number, [number, number, number]]> = [
  [0, [0, 0, 255]],
  [0.25, [0, 255, 255]],
  [0.5, [0, 255, 0]],
  [0.75, [255, 255, 0]],
  [1, [255, 0, 0]],
];

export function jetColor(t: number): [number, number, number] {
  const x = Math.min(1, Math.max(0, t));
  let i = 0;
  while (i < JET_STOPS.length - 2 && x > JET_STOPS[i + 1][0]) i++;
  const [t0, c0] = JET_STOPS[i];
  const [t1, c1] = JET_STOPS[i + 1];
  const f = t1 === t0 ? 0 : (x - t0) / (t1 - t0);
  return [
    Math.round(c0[0] + (c1[0] - c0[0]) * f),
    Math.round(c0[1] + (c1[1] - c0[1]) * f),
    Math.round(c0[2] + (c1[2] - c0[2]) * f),
  ];
}

export function jetCss(t: number, alpha = 1): string {
  const [r, g, b] = jetColor(t);
  return `rgba(${r},${g},${b},${alpha})`;
}
