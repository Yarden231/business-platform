/**
 * Date and number formatting pinned to Israel (ADR-0015).
 *
 * Instants arrive as UTC ISO-8601 and are rendered in `Asia/Jerusalem`.
 * Business dates are calendar dates (`YYYY-MM-DD`) and are never passed
 * through a timezone conversion — a deadline must not slip to the previous
 * day because of DST.
 */
import { DISPLAY_LOCALE, DISPLAY_TIME_ZONE } from '@/lib/constants';

const instantFormatter = new Intl.DateTimeFormat(DISPLAY_LOCALE, {
  dateStyle: 'short',
  timeStyle: 'short',
  timeZone: DISPLAY_TIME_ZONE,
});

const businessDateFormatter = new Intl.DateTimeFormat(DISPLAY_LOCALE, {
  dateStyle: 'long',
  timeZone: 'UTC',
});

const numberFormatter = new Intl.NumberFormat(DISPLAY_LOCALE);

/**
 * Render a UTC instant in Jerusalem local time.
 *
 * `value` is an ISO-8601 string (`2026-09-01T09:12:33Z`) or a `Date`.
 */
export function formatInstant(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  return instantFormatter.format(date);
}

/**
 * Render a business date without shifting it across a timezone.
 *
 * `value` is `YYYY-MM-DD`. It is parsed as UTC midnight so the calendar day
 * the API sent is the calendar day shown, regardless of the browser's zone.
 */
export function formatBusinessDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  const yearText = match?.[1];
  const monthText = match?.[2];
  const dayText = match?.[3];
  if (yearText === undefined || monthText === undefined || dayText === undefined) {
    throw new Error(`Invalid business date: ${value}`);
  }
  return businessDateFormatter.format(
    new Date(Date.UTC(Number(yearText), Number(monthText) - 1, Number(dayText))),
  );
}

/** Format a number with Hebrew grouping (e.g. `1,234`). */
export function formatNumber(value: number): string {
  return numberFormatter.format(value);
}
