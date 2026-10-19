import { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useStore } from '../store';
import { getAnalysis } from '../catalog/analyses';
import UploadDropzone from './UploadDropzone';
import WeatherSelector from './WeatherSelector';
import AnalysisChips from './AnalysisChips';
import ParamControls from './ParamControls';
import ResultsPanel from './ResultsPanel';
import Scene from './Scene';
import EmptyState from './EmptyState';

export default function ProjectWorkspace() {
  const { id } = useParams<{ id: string }>();
  const openProject = useStore((s) => s.openProject);
  const activeProject = useStore((s) => s.activeProject);
  const modelUploaded = useStore((s) => s.modelUploaded);
  const building = useStore((s) => s.building);
  const selectedAnalysis = useStore((s) => s.selectedAnalysis);
  const selectedWeather = useStore((s) => s.selectedWeather);
  const runState = useStore((s) => s.runState);
  const resultsByAnalysis = useStore((s) => s.resultsByAnalysis);
  const run = useStore((s) => s.run);

  useEffect(() => {
    if (id) openProject(id);
  }, [id, openProject]);

  if (!activeProject) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="skeleton h-8 w-48 rounded" />
      </div>
    );
  }

  const needsWeather = getAnalysis(selectedAnalysis).needsWeather;
  const canRun = modelUploaded && (!needsWeather || !!selectedWeather) && runState !== 'running';
  const results = resultsByAnalysis[selectedAnalysis] ?? null;

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Analysis chips bar */}
      <div className="shrink-0 px-4 py-1" style={{ borderBottom: '1px solid var(--slate-200)', background: 'var(--white)' }}>
        <AnalysisChips />
      </div>

      {/* Three-column layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left rail */}
        <aside
          className="w-80 shrink-0 flex flex-col gap-5 p-4 rail-scroll overflow-y-auto"
          style={{ borderRight: '1px solid var(--slate-200)', background: 'var(--white)' }}
        >
          <div>
            <h2 className="font-display font-700 text-base" style={{ fontFamily: 'var(--font-display)', color: 'var(--ink)' }}>
              {activeProject.name}
            </h2>
            <p className="text-xs mt-0.5" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>
              {activeProject.location}
            </p>
            <p className="text-xs mt-0.5" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>
              {activeProject.latitude.toFixed(4)}, {activeProject.longitude.toFixed(4)}
            </p>
          </div>

          <div className="pt-4" style={{ borderTop: '1px solid var(--slate-200)' }}>
            <UploadDropzone />
          </div>

          <div className="pt-4" style={{ borderTop: '1px solid var(--slate-200)' }}>
            <WeatherSelector />
          </div>

          <div className="pt-4" style={{ borderTop: '1px solid var(--slate-200)' }}>
            <ParamControls />
          </div>

          <div className="pt-4 mt-auto" style={{ borderTop: '1px solid var(--slate-200)' }}>
            <button
              onClick={() => run()}
              disabled={!canRun}
              className="w-full h-10 rounded-lg text-sm font-600 flex items-center justify-center gap-2 transition-all"
              style={{
                fontFamily: 'var(--font-display)',
                background: canRun ? 'var(--teal-700)' : 'var(--slate-100)',
                color: canRun ? 'var(--white)' : 'var(--ink-muted)',
                border: 'none',
                cursor: canRun ? 'pointer' : 'not-allowed',
              }}
            >
              {runState === 'running' ? (
                <>
                  <div className="run-track w-20"><span /></div>
                  <span>Running...</span>
                </>
              ) : (
                <span>Run Analysis</span>
              )}
            </button>
            {!modelUploaded && (
              <p className="text-xs mt-2 text-center" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>
                Upload a model to enable
              </p>
            )}
            {modelUploaded && needsWeather && !selectedWeather && (
              <p className="text-xs mt-2 text-center" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>
                Select a weather file to enable
              </p>
            )}
          </div>
        </aside>

        {/* Center — 3D scene */}
        <div className="flex-1 relative overflow-hidden">
          {modelUploaded ? (
            <Scene
              latitude={activeProject.latitude}
              longitude={activeProject.longitude}
              buildings={building}
              results={results}
            />
          ) : (
            <EmptyState title="Upload a model to begin" subtitle="Drop an IFC file in the left panel" icon="upload" />
          )}
        </div>

        {/* Right rail — results */}
        <aside
          className="w-[300px] shrink-0 flex flex-col overflow-hidden"
          style={{ borderLeft: '1px solid var(--slate-200)', background: 'var(--white)' }}
        >
          <ResultsPanel />
        </aside>
      </div>
    </div>
  );
}
