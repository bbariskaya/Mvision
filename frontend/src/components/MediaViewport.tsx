import { CornersOut, ImageSquare } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import type { FaceResult } from "../lib/types";
import { StatusBadge } from "./StatusBadge";

interface Size { width: number; height: number }

interface Props {
  source: string | null;
  faces?: FaceResult[];
  selectedFace?: number;
  onSelectFace?: (index: number) => void;
  label?: string;
}

export function MediaViewport({ source, faces = [], selectedFace = 0, onSelectFace, label = "Image workspace" }: Props) {
  const frameRef = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState<Size>({ width: 0, height: 0 });
  const [media, setMedia] = useState<Size>({ width: 0, height: 0 });

  useEffect(() => {
    const element = frameRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      setViewport({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const scale = media.width && media.height ? Math.min(viewport.width / media.width, viewport.height / media.height) : 0;
  const rendered = { width: media.width * scale, height: media.height * scale };
  const offset = { x: (viewport.width - rendered.width) / 2, y: (viewport.height - rendered.height) / 2 };

  return (
    <section className="relative min-h-[360px] overflow-hidden rounded-2xl bg-ink-950 lg:min-h-[600px]" aria-label={label}>
      <div className="pointer-events-none absolute inset-0 opacity-25" style={{ backgroundImage: "linear-gradient(rgba(89,170,104,.12) 1px, transparent 1px), linear-gradient(90deg, rgba(89,170,104,.12) 1px, transparent 1px)", backgroundSize: "32px 32px" }} />
      <div className="absolute left-4 top-4 z-20 flex items-center gap-2 rounded-full border border-white/10 bg-ink-950/75 px-3 py-2 font-mono text-[10px] uppercase tracking-[.14em] text-ink-300 backdrop-blur">
        <CornersOut size={13} aria-hidden="true" /> Media / overlay plane
      </div>
      <div ref={frameRef} className="absolute inset-0 flex items-center justify-center p-4 sm:p-8">
        {source ? (
          <>
            <img
              src={source}
              alt="Uploaded face recognition source"
              className="max-h-full max-w-full object-contain shadow-2xl shadow-black/40"
              onLoad={(event) => setMedia({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
            />
            {scale > 0 && faces.map((face, index) => {
              const box = face.boundingBox;
              return (
                <button
                  key={`${face.faceId}-${index}`}
                  type="button"
                  aria-label={`Select detected face ${index + 1}`}
                  onClick={() => onSelectFace?.(index)}
                  className="absolute cursor-pointer border-2 transition-colors"
                  style={{
                    left: offset.x + box.x * scale,
                    top: offset.y + box.y * scale,
                    width: box.width * scale,
                    height: box.height * scale,
                    borderColor: index === selectedFace ? "#78cf85" : "rgba(255,255,255,.82)",
                    boxShadow: index === selectedFace ? "0 0 0 2px rgba(7,25,30,.8), 0 0 24px rgba(89,170,104,.4)" : "0 0 0 1px rgba(7,25,30,.8)",
                  }}
                >
                  <span className="absolute -left-0.5 -top-8 whitespace-nowrap"><StatusBadge status={face.status} compact /></span>
                  <span className="absolute bottom-1 right-1 rounded bg-ink-950/80 px-1.5 py-0.5 font-mono text-[9px] text-white">{Math.round(face.confidence * 100)}%</span>
                </button>
              );
            })}
          </>
        ) : (
          <div className="relative z-10 max-w-sm text-center text-ink-300">
            <ImageSquare className="mx-auto mb-5 text-signal-500" size={42} weight="duotone" />
            <h3 className="font-serif text-2xl text-white">A clear field of view.</h3>
            <p className="mt-2 text-sm leading-6">Choose an image to open the media plane. Detections and identity metadata will appear here as independent overlay layers.</p>
          </div>
        )}
      </div>
      {source && <div className="absolute bottom-3 right-4 font-mono text-[10px] text-ink-300">{media.width} × {media.height}px</div>}
    </section>
  );
}
