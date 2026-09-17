import {
  formatResolvedDateRange,
  formatResolvedInstantRange,
  type FormatResolvedRangeOptions,
  type ResolvedDateRange,
  type ResolvedInstantRange,
} from "../utils/resolvedRange";

export type ResolvedRangeLabelProps = FormatResolvedRangeOptions & {
  range?: ResolvedDateRange | null;
  instantRange?: ResolvedInstantRange | null;
  className?: string;
};

export default function ResolvedRangeLabel({
  range,
  instantRange,
  className,
  zone,
  zoneTitle,
  locale,
}: ResolvedRangeLabelProps) {
  const formatted = instantRange
    ? formatResolvedInstantRange(instantRange, { zone, zoneTitle, locale })
    : formatResolvedDateRange(range, { zone, zoneTitle, locale });
  if (!formatted) return null;
  return (
    <span
      className={className ?? "text-[10px] text-sol-base01"}
      title={formatted.title}
    >
      {formatted.text}
    </span>
  );
}
