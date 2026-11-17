interface YovyMarkProps {
  className?: string;
}

/**
 * The Yovy brand mark: three contiguous layers growing upward.
 * Approved at 40 / 28 / 16px; keep the geometry in sync with
 * `web/public/favicon.svg`, which cannot use theme tokens.
 */
export default function YovyMark({ className }: YovyMarkProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" aria-hidden="true">
      <rect className="fill-sol-base00" x="2" y="13" width="6" height="5" rx="1" />
      <rect className="fill-sol-blue" x="2" y="8" width="11" height="5" rx="1" />
      <rect className="fill-sol-base2" x="2" y="3" width="16" height="5" rx="1" />
    </svg>
  );
}
