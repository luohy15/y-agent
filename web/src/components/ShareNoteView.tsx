import { useParams } from "react-router";
import SharedNote from "./SharedNote";

export default function ShareNoteView() {
  const { shareId } = useParams<{ shareId: string }>();
  if (!shareId) return null;
  return (
    <div className="min-h-screen flex flex-col bg-sol-base03 text-sol-base1">
      <SharedNote shareId={shareId} />
    </div>
  );
}
