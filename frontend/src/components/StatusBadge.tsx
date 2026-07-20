import { CheckCircle, CircleNotch, Question, Sparkle } from "@phosphor-icons/react";
import clsx from "clsx";

import type { FaceStatus } from "../lib/types";

const labels: Record<FaceStatus, string> = {
  known: "Known",
  anonymous: "Anonymous",
  new_anonymous: "New anonymous",
};

export function StatusBadge({ status, compact = false }: { status: FaceStatus; compact?: boolean }) {
  const Icon = status === "known" ? CheckCircle : status === "new_anonymous" ? Sparkle : Question;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border font-bold",
        compact ? "px-2 py-1 text-[10px]" : "px-2.5 py-1.5 text-xs",
        status === "known" && "border-signal-200 bg-signal-100 text-signal-700",
        status === "anonymous" && "border-ink-200 bg-ink-100 text-ink-700",
        status === "new_anonymous" && "border-amber-600/20 bg-amber-100 text-amber-600",
      )}
    >
      <Icon size={compact ? 12 : 14} weight="bold" aria-hidden="true" />
      {labels[status]}
    </span>
  );
}

export function WorkingBadge({ label = "Processing" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs font-bold text-ink-700" role="status">
      <CircleNotch className="animate-spin motion-reduce:hidden" size={15} weight="bold" />
      {label}
    </span>
  );
}
