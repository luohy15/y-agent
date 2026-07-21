import { useEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { TransformWrapper, TransformComponent } from "react-zoom-pan-pinch";

const INITIAL_TRANSFORM = { scale: 1, positionX: 0, positionY: 0 };

interface ImageLightboxProps {
  images: string[];
  index: number;
  onClose: () => void;
  onNext: () => void;
  onPrev: () => void;
}

function CloseIcon() {
  return (
    <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function ChevronLeftIcon() {
  return (
    <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="15 18 9 12 15 6" />
    </svg>
  );
}

function ChevronRightIcon() {
  return (
    <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function SpinnerIcon() {
  return (
    <svg className="absolute w-10 h-10 text-white/80 animate-spin" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  );
}

export default function ImageLightbox({ images, index, onClose, onNext, onPrev }: ImageLightboxProps) {
  const [loading, setLoading] = useState(true);
  const [transform, setTransform] = useState(INITIAL_TRANSFORM);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const isOpen = index >= 0 && index < images.length;

  useEffect(() => {
    if (!isOpen) return;

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowLeft") onPrev();
      else if (e.key === "ArrowRight") onNext();
    };

    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [isOpen, onClose, onNext, onPrev]);

  const src = isOpen ? images[index] : null;

  useEffect(() => {
    if (!src) return;
    setLoading(true);
    setTransform(INITIAL_TRANSFORM);
  }, [src]);

  useEffect(() => {
    if (!isOpen || images.length <= 1) return;
    const neighbors = [images[(index + 1) % images.length], images[(index - 1 + images.length) % images.length]];
    neighbors.forEach((url) => {
      if (!url) return;
      const img = new Image();
      img.src = url;
    });
  }, [isOpen, images, index]);

  if (!src) return null;

  const hasMultiple = images.length > 1;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85"
      onClick={onClose}
    >
      <button
        type="button"
        aria-label="Close"
        className="absolute top-4 right-4 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors"
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
      >
        <CloseIcon />
      </button>

      {hasMultiple && (
        <button
          type="button"
          aria-label="Previous image"
          className="absolute left-2 sm:left-4 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors"
          onClick={(e) => {
            e.stopPropagation();
            onPrev();
          }}
        >
          <ChevronLeftIcon />
        </button>
      )}

      <div ref={wrapperRef} className="relative flex items-center justify-center" onClick={(e) => e.stopPropagation()}>
        {loading && <SpinnerIcon />}
        <TransformWrapper
          key={src}
          minScale={1}
          maxScale={8}
          limitToBounds={false}
          doubleClick={{ mode: "reset" }}
          smooth={false}
          wheel={{ step: 0.05 }}
          onTransform={(_, state) => setTransform(state)}
        >
          <TransformComponent wrapperClass="!max-w-[95vw] !max-h-[90vh] !overflow-hidden" contentClass="!flex !items-center !justify-center">
            <img
              src={src}
              alt=""
              className={`max-w-[95vw] max-h-[90vh] object-contain select-none transition-opacity duration-200 ${loading ? "opacity-0" : "opacity-100"}`}
              draggable={false}
              onLoad={() => setLoading(false)}
              onError={() => setLoading(false)}
            />
          </TransformComponent>
        </TransformWrapper>
        {transform.scale > 1.01 && !loading && <MiniMap src={src} transform={transform} wrapperRef={wrapperRef} />}
      </div>

      {hasMultiple && (
        <button
          type="button"
          aria-label="Next image"
          className="absolute right-2 sm:right-4 p-2 rounded-full bg-white/10 hover:bg-white/20 text-white transition-colors"
          onClick={(e) => {
            e.stopPropagation();
            onNext();
          }}
        >
          <ChevronRightIcon />
        </button>
      )}

      {hasMultiple && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-white/10 text-white text-sm">
          {index + 1} / {images.length}
        </div>
      )}
    </div>,
    document.body,
  );
}

interface MiniMapProps {
  src: string;
  transform: { scale: number; positionX: number; positionY: number };
  wrapperRef: RefObject<HTMLDivElement | null>;
}

function MiniMap({ src, transform, wrapperRef }: MiniMapProps) {
  const rect = wrapperRef.current?.getBoundingClientRect();
  if (!rect || rect.width === 0 || rect.height === 0) return null;
  const { scale, positionX, positionY } = transform;
  const W = rect.width;
  const H = rect.height;
  const xMin = Math.max(0, Math.min(W, -positionX / scale));
  const yMin = Math.max(0, Math.min(H, -positionY / scale));
  const xMax = Math.max(0, Math.min(W, (W - positionX) / scale));
  const yMax = Math.max(0, Math.min(H, (H - positionY) / scale));
  const left = (xMin / W) * 100;
  const top = (yMin / H) * 100;
  const width = ((xMax - xMin) / W) * 100;
  const height = ((yMax - yMin) / H) * 100;
  return (
    <div className="absolute top-2 left-2 pointer-events-none overflow-hidden rounded-sm border border-white/60 shadow-lg shadow-black/50" style={{ width: 128 }}>
      <img src={src} alt="" draggable={false} className="block w-full h-auto select-none" />
      <div
        className="absolute border border-white bg-white/20"
        style={{
          left: `${left}%`,
          top: `${top}%`,
          width: `${width}%`,
          height: `${height}%`,
        }}
      />
    </div>
  );
}
