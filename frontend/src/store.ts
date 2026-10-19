/**
 * Microclimate Studio — Zustand store.
 *
 * State: projects, activeProject, modelUploaded, weatherFiles, selectedWeather,
 * selectedAnalysis, params, runState, results (+ offline demo flag).
 *
 * All API calls go through ./api.ts, which falls back to demo data when the
 * backend is unreachable — the UI then carries a "DEMO DATA" indicator.
 */

import { create } from 'zustand';
import type { BuildingPart, ModelStats, Project, Results, WeatherFile } from './api';
import { api } from './api';
import { defaultParamsFor, getAnalysis, type ParamValue } from './catalog/analyses';
import { mockBuilding } from './api';

export type RunState = 'idle' | 'running' | 'success' | 'error';

interface ClimateStore {
  // projects
  projects: Project[] | null; // null = loading
  projectsError: string | null;
  activeProject: Project | null;

  // model
  modelUploaded: boolean;
  uploading: boolean;
  uploadError: string | null;
  modelName: string | null;
  building: BuildingPart[] | null;
  modelStats: ModelStats | null;
  modelWarnings: string[];

  // weather
  weatherFiles: WeatherFile[] | null; // null = loading
  selectedWeather: string | null;

  // analysis config
  selectedAnalysis: string;
  params: Record<string, ParamValue>;

  // run + results
  runState: RunState;
  runError: string | null;
  resultsByAnalysis: Record<string, Results>;

  // demo mode (backend unreachable)
  offline: boolean;

  // actions
  loadProjects: () => Promise<void>;
  createProject: (name: string) => Promise<Project | null>;
  openProject: (id: string) => Promise<void>;
  uploadModel: (file: File) => Promise<void>;
  loadWeather: () => Promise<void>;
  selectWeather: (id: string) => void;
  selectAnalysis: (id: string) => void;
  setParam: (key: string, value: ParamValue) => void;
  run: () => Promise<void>;
  addCustomWeather: (file: File) => Promise<void>;
}

export const useStore = create<ClimateStore>()((set, get) => ({
  projects: null,
  projectsError: null,
  activeProject: null,

  modelUploaded: false,
  uploading: false,
  uploadError: null,
  modelName: null,
  building: null,
  modelStats: null,
  modelWarnings: [],

  weatherFiles: null,
  selectedWeather: null,

  selectedAnalysis: 'wind-speed',
  params: defaultParamsFor('wind-speed'),

  runState: 'idle',
  runError: null,
  resultsByAnalysis: {},

  offline: false,

  loadProjects: async () => {
    set({ projectsError: null });
    try {
      const res = await api.listProjects();
      set({ projects: res.data, offline: get().offline || res.mock });
    } catch (err) {
      set({ projectsError: err instanceof Error ? err.message : 'Failed to load projects.' });
    }
  },

  createProject: async (name) => {
    try {
      const res = await api.createProject(name);
      const p = res.data;
      set((s) => ({ projects: [p, ...(s.projects ?? [])], offline: s.offline || res.mock }));
      return p;
    } catch (err) {
      set({ projectsError: err instanceof Error ? err.message : 'Failed to create project.' });
      return null;
    }
  },

  openProject: async (id) => {
    let list = get().projects;
    if (!list) {
      await get().loadProjects();
      list = get().projects ?? [];
    }
    const found = list.find((p) => p.id === id) ?? null;
    const project =
      found ??
      ({
        id,
        name: `Project ${id.slice(-6)}`,
        location: 'Synthetic sample site',
        description: '',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        analysisCount: 0,
        lastRunAt: null,
        latitude: 10.0,
        longitude: 20.0,
      } satisfies Project);

    set({
      activeProject: project,
      modelUploaded: false,
      uploading: false,
      uploadError: null,
      modelName: null,
      building: null,
      weatherFiles: null,
      selectedWeather: null,
      selectedAnalysis: 'wind-speed',
      params: defaultParamsFor('wind-speed'),
      runState: 'idle',
      runError: null,
      resultsByAnalysis: {},
    });
    await get().loadWeather();
  },

  loadWeather: async () => {
    const project = get().activeProject;
    if (!project) return;
    try {
      const res = await api.listWeather(project.id);
      set((s) => ({
        weatherFiles: res.data,
        offline: s.offline || res.mock,
        selectedWeather:
          s.selectedWeather && res.data.some((w) => w.id === s.selectedWeather)
            ? s.selectedWeather
            : (res.data[0]?.id ?? null),
      }));
    } catch {
      /* weather library failed — selector shows its own empty state */
    }
  },

  uploadModel: async (file) => {
    const project = get().activeProject;
    if (!project) return;
    set({ uploading: true, uploadError: null });
    try {
      const res = await api.uploadModel(project.id, file);
      const { building, latitude, longitude, stats, warnings } = res.data;
      // A georeferenced IFC knows where it stands, so the backend re-centres
      // the project on it — carry that through or the scene flies to the
      // typed-in location and the model sits somewhere else.
      const recentred =
        latitude !== undefined && longitude !== undefined
          ? { ...project, latitude, longitude }
          : project;
      set((s) => ({
        uploading: false,
        modelUploaded: true,
        modelName: res.data.model_name || file.name,
        building: building && building.length > 0 ? building : mockBuilding(project),
        activeProject: recentred,
        projects: (s.projects ?? []).map((p) => (p.id === recentred.id ? recentred : p)),
        modelStats: stats ?? null,
        modelWarnings: warnings ?? [],
        offline: s.offline || res.mock,
      }));
    } catch (err) {
      set({ uploading: false, uploadError: err instanceof Error ? err.message : 'Upload failed.' });
    }
  },

  selectWeather: (id) => set({ selectedWeather: id }),

  selectAnalysis: (id) => {
    set({
      selectedAnalysis: id,
      params: defaultParamsFor(id),
      runState: get().resultsByAnalysis[id] ? 'success' : 'idle',
      runError: null,
    });
  },

  setParam: (key, value) => set((s) => ({ params: { ...s.params, [key]: value } })),

  run: async () => {
    const s = get();
    if (!s.activeProject || !s.modelUploaded || s.runState === 'running') return;
    // Wind speed and sky view factor are geometry-only — requiring a weather
    // file there would block a run the SDK is happy to take.
    if (getAnalysis(s.selectedAnalysis).needsWeather && !s.selectedWeather) return;
    set({ runState: 'running', runError: null });
    try {
      const res = await api.runAnalysis(s.activeProject.id, {
        analysis: s.selectedAnalysis,
        weather_id: s.selectedWeather,
        model_name: s.modelName ?? 'model.ifc',
        params: s.params,
        latitude: s.activeProject.latitude,
        longitude: s.activeProject.longitude,
      });
      set((st) => ({
        resultsByAnalysis: { ...st.resultsByAnalysis, [s.selectedAnalysis]: res.data },
        runState: 'success',
        offline: st.offline || res.mock,
      }));
    } catch (err) {
      set({ runState: 'error', runError: err instanceof Error ? err.message : 'Analysis failed.' });
    }
  },

  addCustomWeather: async (file) => {
    const project = get().activeProject;
    if (!project) return;
    try {
      // The backend stores the EPW next to the project so later runs can read
      // its hourly data — a browser-side parse could not feed a simulation.
      const res = await api.uploadWeather(project.id, file);
      const uploaded: WeatherFile = res.data;
      set((s) => ({
        weatherFiles: [...(s.weatherFiles ?? []).filter((w) => w.id !== uploaded.id), uploaded],
        selectedWeather: uploaded.id,
        offline: s.offline || res.mock,
      }));
    } catch (err) {
      set({ uploadError: err instanceof Error ? err.message : 'Weather upload failed.' });
    }
  },
}));
