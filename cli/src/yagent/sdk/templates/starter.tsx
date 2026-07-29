import { useState } from "react";
import { API, HOST_CONTRACT_VERSION, ListLoading } from "@y/host";

/**
 * Starter UI artifact. Edit this file, then:
 *   y ui publish <slug>
 * The host supplies react / @y/host / swr / recharts via the runtime registry.
 */
export default function StarterPanel() {
  const [count, setCount] = useState(0);

  return (
    <div className="p-4 bg-sol-base02 text-sol-base0 rounded-lg">
      <h2 className="text-lg font-semibold text-sol-base1 mb-2">Starter panel</h2>
      <p className="text-sm text-sol-base01 mb-3">
        Host API: {API} · contract v{HOST_CONTRACT_VERSION}
      </p>
      <button
        type="button"
        onClick={() => setCount((c) => c + 1)}
        className="px-3 py-1 rounded bg-sol-blue text-sol-base03 hover:bg-sol-cyan"
      >
        clicks: {count}
      </button>
      <div className="mt-3">
        <ListLoading />
      </div>
    </div>
  );
}
