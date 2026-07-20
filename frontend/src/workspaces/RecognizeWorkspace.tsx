import { ArrowRight, Scan } from "@phosphor-icons/react";
import { useState } from "react";

import { FaceInspector } from "../components/FaceInspector";
import { ErrorNotice, IdCopy } from "../components/Feedback";
import { FileDropzone } from "../components/FileDropzone";
import { MediaViewport } from "../components/MediaViewport";
import { WorkingBadge } from "../components/StatusBadge";
import { recognize } from "../lib/api";
import type { RecognitionResponse } from "../lib/types";
import { useObjectUrl } from "../lib/useObjectUrl";

export function RecognizeWorkspace() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<RecognitionResponse | null>(null);
  const [selectedFace, setSelectedFace] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const source = useObjectUrl(file);

  function changeFile(next: File | null) {
    setFile(next); setResult(null); setError(null); setSelectedFace(0);
  }

  async function submit() {
    if (!file) return;
    setLoading(true); setError(null);
    try {
      setResult(await recognize(file));
      setSelectedFace(0);
    } catch (caught) {
      setError(caught);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid min-h-0 gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <MediaViewport source={source} faces={result?.faces} selectedFace={selectedFace} onSelectFace={setSelectedFace} label="Recognition image and face overlays" />
      <aside className="flex min-w-0 flex-col gap-4" aria-label="Recognition controls and results">
        <div className="console-card rounded-2xl p-5">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div><p className="text-[10px] font-bold uppercase tracking-[.16em] text-signal-700">Image recognition</p><h2 className="mt-1 text-xl font-bold text-ink-950">Resolve identities</h2></div>
            <Scan className="text-signal-600" size={25} weight="duotone" />
          </div>
          <FileDropzone file={file} onChange={changeFile} disabled={loading} compact={Boolean(file)} />
          <button className="primary-button mt-4 w-full" type="button" disabled={!file || loading} onClick={submit}>
            {loading ? <WorkingBadge label="Analyzing image" /> : <>Run recognition <ArrowRight size={17} weight="bold" /></>}
          </button>
        </div>
        <ErrorNotice error={error} />
        {result && (
          <div className="space-y-3" aria-live="polite">
            <div className="console-card flex items-center justify-between gap-4 rounded-xl p-4">
              <IdCopy value={result.processId} />
              <div className="shrink-0 text-right"><strong className="font-mono text-xl text-ink-950">{result.faceCount}</strong><span className="block text-[10px] uppercase tracking-wider text-ink-500">faces</span></div>
            </div>
            {result.faceCount === 0 ? (
              <div className="rounded-xl border border-ink-200 bg-white/60 p-6 text-center"><strong className="text-sm text-ink-900">No face detected</strong><p className="mt-1 text-xs leading-5 text-ink-500">The request completed successfully, but no face regions were found.</p></div>
            ) : result.faces.map((face, index) => (
              <FaceInspector key={`${face.faceId}-${index}`} face={face} ordinal={index} />
            ))}
          </div>
        )}
      </aside>
    </div>
  );
}
