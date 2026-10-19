import { useRef, useState } from 'react';
import { useStore } from '../store';

export default function UploadDropzone() {
  const uploadModel = useStore((s) => s.uploadModel);
  const uploading = useStore((s) => s.uploading);
  const uploadError = useStore((s) => s.uploadError);
  const modelName = useStore((s) => s.modelName);
  const modelUploaded = useStore((s) => s.modelUploaded);
  const modelStats = useStore((s) => s.modelStats);
  const modelWarnings = useStore((s) => s.modelWarnings);
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleFile = (file: File | null) => {
    if (file && file.name.toLowerCase().endsWith('.ifc')) {
      uploadModel(file);
    } else if (file) {
      alert('Please upload an IFC file');
    }
  };

  if (modelUploaded && modelName) {
    return (
      <div className="p-3 rounded-lg" style={{ background: 'var(--slate-50)', border: '1px solid var(--slate-200)' }}>
        <p className="text-xs font-500 mb-1" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>MODEL</p>
        <p className="text-sm font-500 truncate" style={{ fontFamily: 'var(--font-display)', color: 'var(--ink)' }}>{modelName}</p>
        {modelStats && (
          <div className="mt-2 text-xs space-y-0.5 tabular-nums" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>
            <div className="flex justify-between">
              <span>Buildings</span>
              <span style={{ color: 'var(--ink)' }}>{modelStats.buildings}</span>
            </div>
            <div className="flex justify-between">
              <span>Height</span>
              <span style={{ color: 'var(--ink)' }}>{modelStats.model_height_m.toFixed(1)} m</span>
            </div>
            <div className="flex justify-between">
              <span>Site</span>
              <span style={{ color: 'var(--ink)' }}>
                {Math.round(modelStats.site_width_m)} × {Math.round(modelStats.site_height_m)} m
              </span>
            </div>
            <div className="flex justify-between">
              <span>Triangles</span>
              <span style={{ color: 'var(--ink)' }}>{modelStats.triangles.toLocaleString()}</span>
            </div>
          </div>
        )}
        {/* Parse caveats — missing georeference, oversized site — decide how
            much to trust the run, so they stay on screen, not in a toast. */}
        {modelWarnings.map((warning) => (
          <p key={warning} className="mt-2 text-xs leading-snug" style={{ fontFamily: 'var(--font-mono)', color: 'var(--warning)' }}>
            {warning}
          </p>
        ))}
        <button
          onClick={() => inputRef.current?.click()}
          className="mt-2 text-xs underline"
          style={{ fontFamily: 'var(--font-mono)', color: 'var(--teal-700)', background: 'none', border: 'none', cursor: 'pointer' }}
        >
          Replace model
        </button>
        <input ref={inputRef} type="file" accept=".ifc" className="hidden" onChange={(e) => handleFile(e.target.files?.[0] ?? null)} />
      </div>
    );
  }

  return (
    <div>
      <p className="text-xs font-500 mb-2" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>1. UPLOAD IFC MODEL</p>
      <div
        onClick={() => !uploading && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
        className="flex flex-col items-center justify-center gap-2 p-6 rounded-lg cursor-pointer transition-all"
        style={{
          border: `2px dashed ${dragOver ? 'var(--teal-700)' : 'var(--slate-200)'}`,
          background: dragOver ? 'var(--slate-50)' : 'transparent',
        }}
      >
        {uploading ? (
          <div className="w-full">
            <div className="skeleton h-4 rounded mb-2" />
            <div className="skeleton h-4 rounded w-3/4" />
            <p className="text-xs mt-3 text-center" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>Parsing IFC geometry...</p>
          </div>
        ) : (
          <>
            <svg width="32" height="32" viewBox="0 0 32 32" aria-hidden>
              <path d="M16 8v14M16 8l-6 6M16 8l6 6" stroke="var(--teal-700)" strokeWidth="1.75" fill="none" strokeLinecap="round" />
              <path d="M6 24h20" stroke="var(--teal-700)" strokeWidth="1.75" fill="none" strokeLinecap="round" />
            </svg>
            <p className="text-sm" style={{ fontFamily: 'var(--font-display)', color: 'var(--ink)' }}>Drop IFC file or click to browse</p>
            <p className="text-xs" style={{ fontFamily: 'var(--font-mono)', color: 'var(--ink-muted)' }}>Revit IFC export (.ifc)</p>
          </>
        )}
      </div>
      {uploadError && (
        <p className="mt-2 text-xs" style={{ fontFamily: 'var(--font-mono)', color: 'var(--destructive)' }}>{uploadError}</p>
      )}
      <input ref={inputRef} type="file" accept=".ifc" className="hidden" onChange={(e) => handleFile(e.target.files?.[0] ?? null)} />
    </div>
  );
}
