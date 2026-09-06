/**
 * The message accessor (ADR-0018).
 *
 *     t('auth.login.submit')
 *     t('home.title', { name: user.full_name })
 *
 * Keys are dotted paths into `he`, and `MessageKey` is derived from the catalog
 * itself, so a typo or a renamed group is a compile error rather than an
 * `undefined` rendered into the page.
 *
 * There is no locale argument and no locale routing: Release 1 is Hebrew-only
 * (ADR-0018). Swapping in `next-intl` later replaces this file and adds
 * catalogs; the feature code calling `t()` does not change, which is the whole
 * reason the indirection exists now.
 */
import { he } from '@/messages/he';

/** Every dotted path in `T` whose value is a string. */
type LeafPaths<T> = {
  [K in keyof T & string]: T[K] extends string ? K : `${K}.${LeafPaths<T[K]>}`;
}[keyof T & string];

export type MessageKey = LeafPaths<typeof he>;

export type MessageValues = Readonly<Record<string, string | number>>;

const PLACEHOLDER = /\{(\w+)\}/g;

function resolve(key: string): string {
  let node: unknown = he;
  for (const segment of key.split('.')) {
    if (typeof node !== 'object' || node === null || !(segment in node)) {
      // Unreachable through `t()`, which only accepts `MessageKey`. It exists
      // for the dynamic callers below, which build a key from an API value.
      throw new Error(`Missing Hebrew message for key: ${key}`);
    }
    node = (node as Record<string, unknown>)[segment];
  }
  if (typeof node !== 'string') {
    throw new Error(`Hebrew message key is a group, not a string: ${key}`);
  }
  return node;
}

function interpolate(template: string, values: MessageValues | undefined): string {
  if (values === undefined) {
    return template;
  }
  return template.replace(PLACEHOLDER, (match, name: string) => {
    const value = values[name];
    return value === undefined ? match : String(value);
  });
}

/** The Hebrew string for `key`, with `{placeholders}` replaced by `values`. */
export function t(key: MessageKey, values?: MessageValues): string {
  return interpolate(resolve(key), values);
}

/**
 * The Hebrew string for a key assembled at runtime from an API value — a role
 * name, an error code, a policy issue.
 *
 * Separate from `t()` because the key cannot be checked at compile time here.
 * The caller supplies a fallback, so an unmapped value produces sensible Hebrew
 * instead of an exception in the middle of an error path — which is exactly
 * where an exception is least useful.
 */
export function tDynamic(key: string, fallback: string, values?: MessageValues): string {
  try {
    return interpolate(resolve(key), values);
  } catch {
    return fallback;
  }
}
