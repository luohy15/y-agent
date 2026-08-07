import { ListEmpty } from "./ListStates";
import type { TodoNoteInfo } from "./TraceTodoDetail";

interface PublicNoteListProps {
  items: TodoNoteInfo[];
  onSelectNote: (note: TodoNoteInfo) => void;
}

export default function PublicNoteList({ items, onSelectNote }: PublicNoteListProps) {
  return (
    <div className="flex flex-col h-full text-xs overflow-hidden">
      <div className="flex-1 overflow-y-auto p-1.5">
        {items.length === 0 ? (
          <ListEmpty label="notes" />
        ) : (
          <div className="space-y-0">
            {items.map((note) => {
              const displayName = note.content_key.replace(/^.*\//, "").replace(/\.md$/, "");
              if (!note.share_id) {
                return (
                  <div
                    key={note.note_id}
                    className="w-full text-left flex items-center gap-1.5 py-1 px-1 rounded text-sol-base01 text-[0.7rem] cursor-default opacity-60"
                    title={`${note.content_key} (not shared)`}
                  >
                    <span className="truncate flex-1">{displayName}</span>
                  </div>
                );
              }
              return (
                <button
                  key={note.note_id}
                  onClick={() => onSelectNote(note)}
                  className="w-full text-left flex items-center gap-1.5 py-1 px-1 rounded hover:bg-sol-base02/50 text-sol-base0 hover:text-sol-blue text-[0.7rem] cursor-pointer"
                  title={note.content_key}
                >
                  <span className="truncate flex-1">{displayName}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
