import { useEffect, useState, useRef, useCallback } from "react";
import { PatchDiff } from "@pierre/diffs/react";
import { API, authFetch } from "../api";

interface DiffViewerProps {
  filePath: string;
  vmName?: string | null;
  workDir?: string;
}

interface MarkerBlock {
  startRatio: number;
  endRatio: number;
}

const MINIMAP_WIDTH = 30;
const COL_WIDTH = 8;
const COL_GAP = 1;

function mergeIntoBlocks(ratios: number[], lineHeight: number): MarkerBlock[] {
  if (ratios.length === 0) return [];
  const sorted = [...ratios].sort((a, b) => a - b);
  const blocks: MarkerBlock[] = [];
  let start = sorted[0];
  let end = sorted[0] + lineHeight;

  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] <= end + lineHeight * 0.1) {
      end = sorted[i] + lineHeight;
    } else {
      blocks.push({ startRatio: start, endRatio: end });
      start = sorted[i];
      end = sorted[i] + lineHeight;
    }
  }
  blocks.push({ startRatio: start, endRatio: end });
  return blocks;
}

function findShadowRoot(container: HTMLElement): ParentNode {
  if (container.querySelector("[data-line-type]")) return container;
  const elements = container.querySelectorAll("*");
  for (const el of elements) {
    if (el.shadowRoot) return el.shadowRoot;
  }
  return container;
}

function getTopRelativeTo(el: Element, container: HTMLElement): number {
  let top = 0;
  let current: HTMLElement | null = el as HTMLElement;
  while (current && current !== container) {
    top += current.offsetTop;
    current = current.offsetParent as HTMLElement | null;
  }
  return top;
}

function ScrollbarMarkers({ containerRef }: { containerRef: React.RefObject<HTMLDivElement | null> }) {
  const [deletionBlocks, setDeletionBlocks] = useState<MarkerBlock[]>([]);
  const [additionBlocks, setAdditionBlocks] = useState<MarkerBlock[]>([]);
  const [cursorRatio, setCursorRatio] = useState<number | null>(null);
  const [viewportStart, setViewportStart] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(1);

  const recalculate = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const scrollHeight = container.scrollHeight;
    if (scrollHeight === 0) return;

    // Update viewport indicator
    setViewportStart(container.scrollTop / scrollHeight);
    setViewportHeight(container.clientHeight / scrollHeight);

    const shadowRoot = findShadowRoot(container);

    const additionRatios: number[] = [];
    const deletionRatios: number[] = [];
    let sampleLineHeight = 0;

    shadowRoot.querySelectorAll("[data-line-type='change-addition']").forEach((el) => {
      additionRatios.push(getTopRelativeTo(el, container) / scrollHeight);
      if (!sampleLineHeight) sampleLineHeight = (el as HTMLElement).offsetHeight / scrollHeight;
    });
    shadowRoot.querySelectorAll("[data-line-type='change-deletion']").forEach((el) => {
      deletionRatios.push(getTopRelativeTo(el, container) / scrollHeight);
      if (!sampleLineHeight) sampleLineHeight = (el as HTMLElement).offsetHeight / scrollHeight;
    });

    if (!sampleLineHeight) sampleLineHeight = 20 / scrollHeight;

    setDeletionBlocks(mergeIntoBlocks(deletionRatios, sampleLineHeight));
    setAdditionBlocks(mergeIntoBlocks(additionRatios, sampleLineHeight));

    // Find selected/hovered line for cursor column
    const selected = shadowRoot.querySelector("[data-selected-line]");
    if (selected) {
      setCursorRatio(getTopRelativeTo(selected, container) / scrollHeight);
    } else {
      setCursorRatio(null);
    }
  }, [containerRef]);

  // Track scroll for viewport indicator
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const onScroll = () => {
      const scrollHeight = container.scrollHeight;
      if (scrollHeight === 0) return;
      setViewportStart(container.scrollTop / scrollHeight);
      setViewportHeight(container.clientHeight / scrollHeight);
    };

    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, [containerRef]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const timer = setTimeout(recalculate, 500);

    const observer = new ResizeObserver(recalculate);
    observer.observe(container);

    const mutationObserver = new MutationObserver(() => {
      const elements = container.querySelectorAll("*");
      for (const el of elements) {
        if (el.shadowRoot) {
          shadowMutationObserver.observe(el.shadowRoot, { childList: true, subtree: true });
        }
      }
      recalculate();
    });
    mutationObserver.observe(container, { childList: true, subtree: true });

    const shadowMutationObserver = new MutationObserver(recalculate);
    const elements = container.querySelectorAll("*");
    for (const el of elements) {
      if (el.shadowRoot) {
        shadowMutationObserver.observe(el.shadowRoot, { childList: true, subtree: true });
      }
    }

    return () => {
      clearTimeout(timer);
      observer.disconnect();
      mutationObserver.disconnect();
      shadowMutationObserver.disconnect();
    };
  }, [containerRef, recalculate]);

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientY - rect.top) / rect.height;
    container.scrollTop = ratio * container.scrollHeight - container.clientHeight / 2;
  };

  const MIN_HEIGHT = 3;
  const col1Left = 2;
  const col2Left = col1Left + COL_WIDTH + COL_GAP;
  const col3Left = col2Left + COL_WIDTH + COL_GAP;

  return (
    <div
      onClick={handleClick}
      style={{
        position: "absolute",
        right: 0,
        top: 0,
        width: `${MINIMAP_WIDTH}px`,
        height: "100%",
        cursor: "pointer",
        zIndex: 10,
        backgroundColor: "rgba(0, 43, 54, 0.5)",
      }}
    >
      {/* Viewport indicator — white translucent bar spanning all 3 columns */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: `${viewportStart * 100}%`,
          width: "100%",
          height: `${viewportHeight * 100}%`,
          backgroundColor: "rgba(147, 161, 161, 0.15)",
          borderTop: "1px solid rgba(147, 161, 161, 0.3)",
          borderBottom: "1px solid rgba(147, 161, 161, 0.3)",
          pointerEvents: "none",
        }}
      />

      {/* Column 1: Current selection cursor */}
      {cursorRatio !== null && (
        <div
          style={{
            position: "absolute",
            left: `${col1Left}px`,
            top: `${cursorRatio * 100}%`,
            width: `${COL_WIDTH}px`,
            height: `${MIN_HEIGHT}px`,
            backgroundColor: "rgba(181, 137, 0, 0.8)",
          }}
        />
      )}

      {/* Column 2: Deletions (red) */}
      {deletionBlocks.map((b, i) => (
        <div
          key={`d${i}`}
          style={{
            position: "absolute",
            left: `${col2Left}px`,
            top: `${b.startRatio * 100}%`,
            width: `${COL_WIDTH}px`,
            minHeight: `${MIN_HEIGHT}px`,
            height: `${(b.endRatio - b.startRatio) * 100}%`,
            backgroundColor: "rgba(206, 71, 64, 0.65)",
          }}
        />
      ))}

      {/* Column 3: Additions (green) */}
      {additionBlocks.map((b, i) => (
        <div
          key={`a${i}`}
          style={{
            position: "absolute",
            left: `${col3Left}px`,
            top: `${b.startRatio * 100}%`,
            width: `${COL_WIDTH}px`,
            minHeight: `${MIN_HEIGHT}px`,
            height: `${(b.endRatio - b.startRatio) * 100}%`,
            backgroundColor: "rgba(80, 158, 47, 0.65)",
          }}
        />
      ))}
    </div>
  );
}

export default function DiffViewer({ filePath, vmName, workDir }: DiffViewerProps) {
  const [diff, setDiff] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const vmQuery = (vmName ? `&vm_name=${encodeURIComponent(vmName)}` : "") + (workDir ? `&work_dir=${encodeURIComponent(workDir)}` : "");

  useEffect(() => {
    setLoading(true);
    setError(null);
    setDiff(null);
    authFetch(`${API}/api/git/diff?path=${encodeURIComponent(filePath)}${vmQuery}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch diff");
        return res.json();
      })
      .then((data) => {
        setDiff(data.diff || "");
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, [filePath, vmQuery]);

  if (loading) {
    return <p className="text-sol-base01 italic text-sm p-3">Loading diff...</p>;
  }
  if (error) {
    return <p className="text-sol-red text-sm p-3">{error}</p>;
  }
  if (!diff) {
    return <p className="text-sol-base01 text-sm p-3">No changes</p>;
  }

  return (
    <div className="h-full flex">
      <div ref={containerRef} className="h-full overflow-auto flex-1">
        <PatchDiff patch={diff} options={{ theme: "solarized-dark" }} />
      </div>
      <ScrollbarMarkers containerRef={containerRef} />
    </div>
  );
}
