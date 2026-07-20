import { IdentificationCard, UserPlus } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";

import { ErrorNotice, IdCopy } from "../components/Feedback";
import { FileDropzone } from "../components/FileDropzone";
import { MediaViewport } from "../components/MediaViewport";
import { WorkingBadge } from "../components/StatusBadge";
import { enroll } from "../lib/api";
import type { RecognitionResponse } from "../lib/types";
import { useObjectUrl } from "../lib/useObjectUrl";

export function EnrollWorkspace() {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [faceId, setFaceId] = useState("");
  const [metadata, setMetadata] = useState("{}");
  const [result, setResult] = useState<RecognitionResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const source = useObjectUrl(file);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !name.trim()) return;
    setLoading(true); setError(null);
    try {
      const parsed = JSON.parse(metadata) as unknown;
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("Metadata must be a JSON object.");
      setResult(await enroll(file, name.trim(), parsed as Record<string, unknown>, faceId || undefined));
    } catch (caught) {
      setError(caught);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid min-h-0 gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <MediaViewport source={source} faces={result?.faces} label="Enrollment image and resulting face overlay" />
      <aside className="space-y-4">
        <form className="console-card rounded-2xl p-5" onSubmit={submit}>
          <div className="mb-5 flex items-start justify-between gap-4">
            <div><p className="text-[10px] font-bold uppercase tracking-[.16em] text-signal-700">Enrollment</p><h2 className="mt-1 text-xl font-bold text-ink-950">Name one identity</h2></div>
            <UserPlus className="text-signal-600" size={25} weight="duotone" />
          </div>
          <FileDropzone file={file} onChange={(next) => { setFile(next); setResult(null); }} disabled={loading} compact />
          <div className="mt-4"><label className="label" htmlFor="enroll-name">Name</label><input className="field" id="enroll-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Full display name" required maxLength={255} /></div>
          <div className="mt-4"><label className="label" htmlFor="enroll-face-id">Existing anonymous face ID <span className="normal-case tracking-normal text-ink-500">(optional)</span></label><input className="field font-mono text-xs" id="enroll-face-id" value={faceId} onChange={(event) => setFaceId(event.target.value)} placeholder="UUID to preserve" /></div>
          <div className="mt-4"><label className="label" htmlFor="enroll-metadata">Metadata JSON</label><textarea className="field min-h-24 resize-y font-mono text-xs leading-5" id="enroll-metadata" value={metadata} onChange={(event) => setMetadata(event.target.value)} spellCheck={false} /></div>
          <button className="primary-button mt-5 w-full" type="submit" disabled={!file || !name.trim() || loading}>{loading ? <WorkingBadge label="Creating identity" /> : <><IdentificationCard size={18} weight="bold" /> Enroll identity</>}</button>
        </form>
        <ErrorNotice error={error} />
        {result && (
          <div className="rounded-2xl border border-signal-200 bg-signal-100 p-5" aria-live="polite">
            <p className="text-[10px] font-bold uppercase tracking-[.14em] text-signal-700">Enrollment complete</p>
            <h3 className="mt-1 text-lg font-bold text-ink-950">{result.faces[0]?.name}</h3>
            <div className="mt-4 space-y-3 border-t border-signal-200 pt-4"><IdCopy value={result.faces[0].faceId} label="Face ID" /><IdCopy value={result.processId} /></div>
          </div>
        )}
      </aside>
    </div>
  );
}
