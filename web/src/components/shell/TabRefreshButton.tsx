/** Host-owned tab refresh control (todo 3674). One icon, one spinner,
 * used by FileViewer and the public demo shell. */
export default function TabRefreshButton({
  title,
  spinning,
  onClick,
}: {
  title: string;
  spinning: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={spinning}
      className={`text-sol-base01 hover:text-sol-base1 cursor-pointer p-0.5 ml-2 shrink-0 disabled:cursor-default ${spinning ? "animate-spin" : ""}`}
      title={title}
      aria-label={title}
    >
      <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
        <path d="M8 1a7 7 0 0 1 7 7h-1.5A5.5 5.5 0 0 0 8 2.5V5L4.5 2 8 -1v2zm0 14a7 7 0 0 1-7-7h1.5A5.5 5.5 0 0 0 8 13.5V11l3.5 3L8 17v-2z" />
      </svg>
    </button>
  );
}
