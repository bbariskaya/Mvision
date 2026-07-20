import { Copy, WarningCircle } from "@phosphor-icons/react";
import { useState } from "react";

import { ApiError } from "../lib/api";

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "An unexpected error occurred.";
  const processId = error instanceof ApiError ? error.processId : null;
  return (
    <div className="rounded-xl border border-alert-600/20 bg-alert-100 p-4 text-sm text-alert-600" role="alert">
      <div className="flex gap-3">
        <WarningCircle className="mt-0.5 shrink-0" size={18} weight="fill" />
        <div>
          <strong className="block">Request could not be completed</strong>
          <p className="mt-1 leading-5">{message}</p>
          {processId && <p className="mt-2 font-mono text-[10px]">Process {processId}</p>}
        </div>
      </div>
    </div>
  );
}

export function IdCopy({ value, label = "Process ID" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }
  return (
    <button type="button" onClick={copy} className="group flex min-w-0 items-center gap-2 text-left" aria-label={`Copy ${label}`}>
      <span className="min-w-0">
        <span className="block text-[10px] font-bold uppercase tracking-[.12em] text-ink-500">{copied ? "Copied" : label}</span>
        <span className="block truncate font-mono text-[11px] text-ink-800">{value}</span>
      </span>
      <Copy className="shrink-0 text-ink-500 transition-colors group-hover:text-signal-700" size={16} />
    </button>
  );
}
