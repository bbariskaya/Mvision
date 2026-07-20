import { ImageSquare, UploadSimple } from "@phosphor-icons/react";
import clsx from "clsx";
import { useRef, useState } from "react";

interface Props {
  file: File | null;
  onChange: (file: File | null) => void;
  disabled?: boolean;
  compact?: boolean;
}

export function FileDropzone({ file, onChange, disabled = false, compact = false }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function choose(files: FileList | null) {
    const selected = files?.[0];
    if (selected) onChange(selected);
  }

  return (
    <div
      className={clsx(
        "group relative flex w-full cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed text-center transition-colors",
        compact ? "min-h-32 px-4 py-5" : "min-h-48 px-6 py-8",
        dragging ? "border-signal-600 bg-signal-100" : "border-ink-300 bg-white/45 hover:border-signal-600 hover:bg-white/70",
        disabled && "pointer-events-none opacity-50",
      )}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-label="Choose a JPEG image"
      onClick={() => inputRef.current?.click()}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") inputRef.current?.click();
      }}
      onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => { event.preventDefault(); setDragging(false); choose(event.dataTransfer.files); }}
    >
      <input
        ref={inputRef}
        className="sr-only"
        type="file"
        accept="image/jpeg,.jpg,.jpeg"
        disabled={disabled}
        onChange={(event) => choose(event.target.files)}
      />
      <span className="mb-4 grid size-11 place-items-center rounded-full bg-ink-900 text-white shadow-lg shadow-ink-900/10">
        {file ? <ImageSquare size={22} weight="duotone" /> : <UploadSimple size={22} weight="bold" />}
      </span>
      <strong className="max-w-full truncate text-sm text-ink-900">{file ? file.name : "Drop a JPEG here"}</strong>
      <span className="mt-1.5 text-xs leading-5 text-ink-500">{file ? `${(file.size / 1024).toFixed(0)} KB · Click to replace` : "or click to browse · maximum 10 MB"}</span>
    </div>
  );
}
