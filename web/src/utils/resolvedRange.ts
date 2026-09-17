export type ResolvedDateRange = {
  input?: string | null;
  recognized?: boolean;
  from_date?: string | null;
  to_date?: string | null;
};

export type FormatResolvedRangeOptions = {
  /** Visible compact zone suffix (surfaces 3-7). Surfaces 1-2 omit this. */
  zone?: string | null;
  /** Longer zone attribution for the tooltip; defaults to `zone`. */
  zoneTitle?: string | null;
  locale?: string;
};

export type FormattedResolvedRange = {
  text: string;
  title: string;
};

const DATE_OPTS: Intl.DateTimeFormatOptions = {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
};

const INSTANT_OPTS: Intl.DateTimeFormatOptions = {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZone: "UTC",
};

function parseIsoDate(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return null;
  }
  return date;
}

function formatDay(date: Date, locale: string): string {
  return date.toLocaleDateString(locale, DATE_OPTS);
}

function compactRange(from: Date, to: Date, locale: string): string {
  const fromText = formatDay(from, locale);
  const toText = formatDay(to, locale);
  if (fromText === toText) return fromText;
  if (from.getUTCFullYear() === to.getUTCFullYear()) {
    if (from.getUTCMonth() === to.getUTCMonth()) {
      const month = from.toLocaleDateString(locale, { month: "short", timeZone: "UTC" });
      return `${month} ${from.getUTCDate()} - ${to.getUTCDate()}, ${from.getUTCFullYear()}`;
    }
    const fromShort = from.toLocaleDateString(locale, {
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
    return `${fromShort} - ${toText}`;
  }
  return `${fromText} - ${toText}`;
}

function withZone(text: string, zone?: string | null): string {
  const trimmed = zone?.trim();
  return trimmed ? `${text} (${trimmed})` : text;
}

function isoTitle(
  fromDate: string | null | undefined,
  toDate: string | null | undefined,
  zone?: string | null,
): string {
  const from = fromDate || "…";
  const to = toDate || "…";
  const range = fromDate && toDate && fromDate === toDate ? from : `${from} – ${to}`;
  return withZone(range, zone);
}

function quoteInput(input: string): string {
  return JSON.stringify(input);
}

/**
 * Compact inclusive date-range label (todo 3580 D7).
 * `from_date`/`to_date` are calendar dates, never reinterpreted into another zone.
 */
export function formatResolvedDateRange(
  range: ResolvedDateRange | null | undefined,
  options: FormatResolvedRangeOptions = {},
): FormattedResolvedRange | null {
  if (!range) return null;
  const locale = options.locale ?? "en-US";
  const zone = options.zone ?? null;
  const zoneTitle = options.zoneTitle ?? zone;
  const input = (range.input ?? "").trim();

  if (range.recognized === false) {
    const quoted = input ? quoteInput(input) : "input";
    return {
      text: `Unrecognized ${quoted}`,
      title: withZone(`Unrecognized ${quoted}`, zoneTitle),
    };
  }

  const fromDate = range.from_date ?? null;
  const toDate = range.to_date ?? null;
  if (!fromDate && !toDate) {
    return { text: withZone("All time", zone), title: withZone("All time", zoneTitle) };
  }
  if (!fromDate && toDate) {
    const to = parseIsoDate(toDate);
    if (!to) return null;
    const text = `through ${formatDay(to, locale)}`;
    return { text: withZone(text, zone), title: isoTitle(fromDate, toDate, zoneTitle) };
  }
  if (fromDate && !toDate) {
    const from = parseIsoDate(fromDate);
    if (!from) return null;
    const text = `from ${formatDay(from, locale)}`;
    return { text: withZone(text, zone), title: isoTitle(fromDate, toDate, zoneTitle) };
  }
  const from = parseIsoDate(fromDate!);
  const to = parseIsoDate(toDate!);
  if (!from || !to) return null;
  return {
    text: withZone(compactRange(from, to, locale), zone),
    title: isoTitle(fromDate, toDate, zoneTitle),
  };
}

export type ResolvedInstantRange = {
  recognized?: boolean;
  input?: string | null;
  start?: string | Date | number | null;
  end?: string | Date | number | null;
};

function isAbsentInstant(value: string | Date | number | null | undefined): boolean {
  return value == null || value === "";
}

function toDate(value: string | Date | number): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatInstant(date: Date, locale: string, timeZone?: string | null): string {
  return date.toLocaleString(locale, {
    ...INSTANT_OPTS,
    ...(timeZone ? { timeZone } : {}),
  });
}

/**
 * Compact inclusive instant-range label for server/UTC windows (monitor).
 * Instants are formatted in `zone` when given, otherwise UTC.
 */
export function formatResolvedInstantRange(
  range: ResolvedInstantRange | null | undefined,
  options: FormatResolvedRangeOptions = {},
): FormattedResolvedRange | null {
  if (!range) return null;
  const locale = options.locale ?? "en-US";
  const zone = options.zone ?? null;
  const zoneTitle = options.zoneTitle ?? zone;
  const input = (range.input ?? "").trim();
  if (range.recognized === false) {
    const quoted = input ? quoteInput(input) : "input";
    return {
      text: `Unrecognized ${quoted}`,
      title: withZone(`Unrecognized ${quoted}`, zoneTitle),
    };
  }
  const startAbsent = isAbsentInstant(range.start);
  const endAbsent = isAbsentInstant(range.end);
  const start = startAbsent ? null : toDate(range.start as string | Date | number);
  const end = endAbsent ? null : toDate(range.end as string | Date | number);
  if (!startAbsent && !start) return null;
  if (!endAbsent && !end) return null;
  if (!start && !end) {
    return { text: withZone("All time", zone), title: withZone("All time", zoneTitle) };
  }
  const timeZone = zone || "UTC";
  if (!start && end) {
    const text = `through ${formatInstant(end, locale, timeZone)}`;
    return { text: withZone(text, zone), title: withZone(end.toISOString(), zoneTitle) };
  }
  if (start && !end) {
    const text = `from ${formatInstant(start, locale, timeZone)}`;
    return { text: withZone(text, zone), title: withZone(start.toISOString(), zoneTitle) };
  }
  const text = `${formatInstant(start!, locale, timeZone)} - ${formatInstant(end!, locale, timeZone)}`;
  return {
    text: withZone(text, zone),
    title: withZone(`${start!.toISOString()} – ${end!.toISOString()}`, zoneTitle),
  };
}
