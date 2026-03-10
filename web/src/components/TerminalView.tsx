import { useEffect, useRef, useState } from "react";
import { API, authFetch } from "../api";

interface TerminalViewProps {
  isLoggedIn: boolean;
  vmName: string | null;
  workDir?: string;
}

export default function TerminalView({ isLoggedIn, vmName, workDir }: TerminalViewProps) {
  const [output, setOutput] = useState("");
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const outputRef = useRef<HTMLPreElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [output]);

  useEffect(() => {
    if (!running) inputRef.current?.focus();
  }, [running]);

  const runCommand = async () => {
    const cmd = input.trim();
    if (!cmd || !isLoggedIn) return;
    setInput("");
    setOutput((prev) => prev + `$ ${cmd}\n`);
    setRunning(true);

    const params = new URLSearchParams();
    if (vmName) params.set("vm_name", vmName);
    if (workDir) params.set("work_dir", workDir);

    try {
      const res = await authFetch(`${API}/api/terminal/run?${params}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: cmd }),
      });
      const data = await res.json();
      setOutput((prev) => prev + (data.output || "") + "\n");
    } catch {
      setOutput((prev) => prev + "Error: failed to run command\n");
    } finally {
      setRunning(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runCommand();
    } else if (e.ctrlKey) {
      const el = e.currentTarget;
      const pos = el.selectionStart ?? 0;
      const val = el.value;
      switch (e.key) {
        case "u": {
          e.preventDefault();
          setInput(val.slice(pos));
          requestAnimationFrame(() => el.setSelectionRange(0, 0));
          break;
        }
        case "w": {
          e.preventDefault();
          let start = pos;
          while (start > 0 && /\s/.test(val[start - 1])) start--;
          while (start > 0 && !/\s/.test(val[start - 1])) start--;
          setInput(val.slice(0, start) + val.slice(pos));
          requestAnimationFrame(() => el.setSelectionRange(start, start));
          break;
        }
      }
    }
  };

  return (
    <div ref={outputRef} className="h-full overflow-auto bg-sol-base03" onClick={() => inputRef.current?.focus()}>
      <pre className="p-2 text-sol-base0 font-mono text-sm whitespace-pre-wrap break-all">
        {output || (isLoggedIn ? "" : "Login to use terminal.\n")}
      </pre>
      <div className="flex items-center gap-2 px-2 py-1.5 shrink-0">
        <span className="text-sol-base01 text-sm">$</span>
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          className="flex-1 bg-transparent text-sol-base0 font-mono text-sm outline-none placeholder:text-sol-base01"
          placeholder={running ? "running..." : "type command..."}
          disabled={!isLoggedIn || running}
          autoFocus
        />
      </div>
    </div>
  );
}
