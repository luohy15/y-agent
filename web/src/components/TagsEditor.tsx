import { useMemo, useState, type KeyboardEvent } from "react";

export interface TagsEditorProps {
  value: string[];
  onChange: (next: string[]) => void;
  /**
   * Canonical vocabulary. When provided, a filtered autocomplete list is
   * shown on focus / typing. Used as the allow-list when `allowNew` is false.
   */
  suggestions?: readonly string[];
  /**
   * When true (default), any trimmed non-empty string can be committed.
   * When false, a commit must match `suggestions` (case-insensitive; the
   * canonical suggestion spelling is stored). Unknown values are rejected
   * with an inline hint. Tags already in `value` stay until removed.
   */
  allowNew?: boolean;
}

export type TagCommitResult =
  | { kind: "noop" }
  | { kind: "add"; tag: string }
  | { kind: "reject"; hint: string };

export const VOCABULARY_UNAVAILABLE_HINT = "Tag vocabulary is unavailable.";

export function vocabularyUnavailable(
  allowNew: boolean | undefined,
  suggestions: readonly string[] | undefined,
): boolean {
  return allowNew === false && !suggestions?.length;
}

export function resolveTagCommit(
  raw: string,
  value: string[],
  options: { allowNew?: boolean; suggestions?: readonly string[] } = {},
): TagCommitResult {
  const trimmed = raw.trim();
  if (!trimmed) return { kind: "noop" };
  const allowNew = options.allowNew !== false;
  if (allowNew) {
    if (value.includes(trimmed)) return { kind: "noop" };
    return { kind: "add", tag: trimmed };
  }
  if (vocabularyUnavailable(false, options.suggestions)) {
    return { kind: "reject", hint: VOCABULARY_UNAVAILABLE_HINT };
  }
  const canonical =
    options.suggestions?.find((s) => s === trimmed) ??
    options.suggestions?.find((s) => s.toLowerCase() === trimmed.toLowerCase());
  if (!canonical) {
    return { kind: "reject", hint: `"${trimmed}" is not an existing tag` };
  }
  if (value.includes(canonical)) return { kind: "noop" };
  return { kind: "add", tag: canonical };
}

const SUGGESTION_LIMIT = 20;

export function filterTagSuggestions(
  query: string,
  suggestions: readonly string[] | undefined,
  selected: readonly string[],
  limit = SUGGESTION_LIMIT,
): string[] {
  if (!suggestions?.length) return [];
  const taken = new Set(selected);
  const q = query.trim().toLowerCase();
  const exact: string[] = [];
  const rest: string[] = [];
  for (const tag of suggestions) {
    if (taken.has(tag)) continue;
    const lower = tag.toLowerCase();
    if (q) {
      if (lower === q) {
        exact.push(tag);
        continue;
      }
      if (!lower.includes(q)) continue;
    }
    rest.push(tag);
  }
  return [...exact, ...rest].slice(0, limit);
}

function pickMatch(
  matches: readonly string[],
  index: number,
  value: string[],
  options: { allowNew?: boolean; suggestions?: readonly string[] },
): TagCommitResult | null {
  const picked = matches[index] ?? matches[0];
  if (!picked) return null;
  return resolveTagCommit(picked, value, options);
}

export function resolveEnterCommit(
  raw: string,
  value: string[],
  options: {
    allowNew?: boolean;
    suggestions?: readonly string[];
    matches: readonly string[];
    highlight: number;
    highlightMoved: boolean;
    listOpen?: boolean;
  },
): TagCommitResult {
  const typed = resolveTagCommit(raw, value, options);
  const trimmed = raw.trim();
  const listOpen = options.listOpen ?? options.matches.length > 0;
  // 1. An arrowed-to row always wins, including over an exact typed tag (F2).
  if (options.highlightMoved) {
    return pickMatch(options.matches, options.highlight, value, options) ?? typed;
  }
  // 2. Exact typed hit (add or already-attached noop) keeps rounds 2+3 closed.
  const typedExact =
    typed.kind === "noop" ||
    (typed.kind === "add" && typed.tag.toLowerCase() === trimmed.toLowerCase());
  if (typedExact) return typed;
  // 3. Open list: Enter accepts the top row without requiring ArrowDown (F1).
  if (listOpen && options.matches.length > 0) {
    return pickMatch(options.matches, 0, value, options) ?? typed;
  }
  // 4. Typed result: reject, or free-text add when allowNew.
  return typed;
}

export default function TagsEditor({
  value,
  onChange,
  suggestions,
  allowNew = true,
}: TagsEditorProps) {
  const [tagInput, setTagInput] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [highlightMoved, setHighlightMoved] = useState(false);

  const vocabMissing = vocabularyUnavailable(allowNew, suggestions);
  const matches = useMemo(
    () => filterTagSuggestions(tagInput, suggestions, value),
    [tagInput, suggestions, value],
  );
  const showList = !vocabMissing && Boolean(suggestions) && open && matches.length > 0;
  const shownHint = vocabMissing ? VOCABULARY_UNAVAILABLE_HINT : hint;

  const applyCommit = (result: TagCommitResult) => {
    if (result.kind === "add") {
      onChange([...value, result.tag]);
      setTagInput("");
      setHint(null);
      setHighlight(0);
      setHighlightMoved(false);
      return;
    }
    if (result.kind === "reject") {
      setHint(result.hint);
      return;
    }
    setTagInput("");
    setHint(null);
    setHighlight(0);
    setHighlightMoved(false);
  };

  const addTag = (raw: string = tagInput) => {
    applyCommit(resolveTagCommit(raw, value, { allowNew, suggestions }));
  };

  const pickSuggestion = (tag: string) => {
    applyCommit(resolveTagCommit(tag, value, { allowNew, suggestions }));
  };

  const removeTag = (tag: string) => {
    onChange(value.filter((x) => x !== tag));
  };

  const onTagKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (showList && e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((i) => (i + 1) % matches.length);
      setHighlightMoved(true);
      return;
    }
    if (showList && e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((i) => (i - 1 + matches.length) % matches.length);
      setHighlightMoved(true);
      return;
    }
    if (e.key === "Escape") {
      if (open) {
        e.preventDefault();
        setOpen(false);
        setHighlightMoved(false);
      }
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      applyCommit(resolveEnterCommit(tagInput, value, {
        allowNew,
        suggestions,
        matches,
        highlight,
        highlightMoved,
        listOpen: showList,
      }));
      return;
    }
    if (e.key === "Backspace" && tagInput === "" && value.length > 0) {
      e.preventDefault();
      onChange(value.slice(0, -1));
    }
  };

  return (
    <div className="relative min-w-0">
      <div className="flex flex-wrap gap-1 items-center bg-sol-base03 border border-sol-base01/30 rounded px-1.5 py-1 focus-within:border-sol-blue">
        {value.map((tag) => (
          <span key={tag} className="inline-flex items-center gap-0.5 bg-sol-base02 text-sol-base0 pl-1.5 pr-1 py-0.5 rounded text-[0.65rem]">
            {tag}
            <button
              onClick={() => removeTag(tag)}
              className="text-sol-base01 hover:text-sol-red cursor-pointer leading-none"
              title="Remove tag"
            >
              ×
            </button>
          </span>
        ))}
        <input
          value={tagInput}
          onChange={(e) => {
            setTagInput(e.target.value);
            setHighlight(0);
            setHighlightMoved(false);
            setOpen(true);
            if (hint) setHint(null);
          }}
          onKeyDown={onTagKeyDown}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            if (tagInput.trim()) addTag();
            setOpen(false);
          }}
          placeholder={value.length === 0 ? "Add tags..." : ""}
          className="flex-1 min-w-[4rem] bg-transparent text-sol-base1 text-xs outline-none disabled:opacity-50"
          autoComplete="off"
          disabled={vocabMissing}
          role={suggestions?.length ? "combobox" : undefined}
          aria-expanded={suggestions?.length ? showList : undefined}
          aria-autocomplete={suggestions?.length ? "list" : undefined}
        />
        {shownHint && (
          <span className="w-full text-[0.6rem] text-sol-red">{shownHint}</span>
        )}
      </div>
      {showList && (
        <ul
          role="listbox"
          className="absolute z-20 left-0 right-0 mt-0.5 max-h-40 overflow-y-auto bg-sol-base03 border border-sol-base01 rounded shadow-float py-0.5"
        >
          {matches.map((tag, i) => (
            <li
              key={tag}
              role="option"
              aria-selected={i === highlight}
              onMouseDown={(e) => {
                e.preventDefault();
                pickSuggestion(tag);
              }}
              onMouseEnter={() => setHighlight(i)}
              className={`px-1.5 py-0.5 text-[0.65rem] cursor-pointer ${
                i === highlight ? "bg-sol-base02 text-sol-base1" : "text-sol-base0"
              }`}
            >
              {tag}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
