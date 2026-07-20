import { Fingerprint, MapPin } from "@phosphor-icons/react";

import type { FaceResult } from "../lib/types";
import { IdCopy } from "./Feedback";
import { StatusBadge } from "./StatusBadge";

export function FaceInspector({ face, ordinal }: { face: FaceResult; ordinal: number }) {
  return (
    <article className="console-card rounded-xl p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[.13em] text-ink-500">Detection {String(ordinal + 1).padStart(2, "0")}</p>
          <h3 className="mt-1 text-base font-bold text-ink-950">{face.name ?? "Unlabelled identity"}</h3>
        </div>
        <StatusBadge status={face.status} />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2">
        <div className="rounded-lg bg-ink-100/70 p-3">
          <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-ink-500"><Fingerprint size={13} /> Match</span>
          <strong className="mt-1 block font-mono text-sm text-ink-900">{(face.confidence * 100).toFixed(1)}%</strong>
        </div>
        <div className="rounded-lg bg-ink-100/70 p-3">
          <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-ink-500"><MapPin size={13} /> Region</span>
          <strong className="mt-1 block font-mono text-[11px] text-ink-900">{Math.round(face.boundingBox.width)} × {Math.round(face.boundingBox.height)}</strong>
        </div>
      </div>
      <div className="mt-4 border-t border-ink-100 pt-3"><IdCopy value={face.faceId} label="Face ID" /></div>
      {face.metadata && Object.keys(face.metadata).length > 0 && (
        <dl className="mt-4 space-y-2 border-t border-ink-100 pt-3">
          {Object.entries(face.metadata).map(([key, value]) => (
            <div key={key} className="flex items-baseline justify-between gap-4 text-xs">
              <dt className="text-ink-500">{key}</dt><dd className="truncate font-semibold text-ink-800">{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </article>
  );
}
