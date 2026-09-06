/**
 * Map an API failure onto Hebrew copy (ADR-0014).
 *
 * Feature code never reads `error.message` — that field is English and
 * developer-facing. Everything a user sees comes from the catalog.
 */
import { MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH } from '@/lib/constants';
import { ApiError, NetworkError } from '@/lib/api/errors';
import type { PasswordIssue } from '@/lib/api/types';
import { t, tDynamic } from '@/messages/t';

const PASSWORD_ISSUES = new Set<string>([
  'too_short',
  'too_long',
  'common',
  'whitespace_only',
  'same_as_current',
]);

function isPasswordIssue(issue: string): issue is PasswordIssue {
  return PASSWORD_ISSUES.has(issue);
}

/** Hebrew for a thrown API or network failure. */
export function messageForError(error: unknown): string {
  if (error instanceof NetworkError) {
    return t('errors.network');
  }
  if (error instanceof ApiError) {
    return tDynamic(`errors.codes.${error.code}`, t('errors.unexpected'));
  }
  return t('errors.unexpected');
}

/** Hebrew for one `PASSWORD_INVALID` details entry, with policy bounds filled in. */
export function messageForPasswordIssue(issue: string): string {
  if (!isPasswordIssue(issue)) {
    return t('errors.codes.PASSWORD_INVALID');
  }
  return t(`errors.passwordIssues.${issue}`, {
    min: MIN_PASSWORD_LENGTH,
    max: MAX_PASSWORD_LENGTH,
  });
}

/**
 * Field-level Hebrew for a password-change failure.
 *
 * `CURRENT_PASSWORD_INVALID` attaches to the current-password field.
 * `PASSWORD_INVALID` details attach to the new-password field. Anything else
 * is a form-level message.
 */
export function fieldMessagesForPasswordError(error: unknown): {
  currentPassword?: string;
  newPassword?: string;
  form?: string;
} {
  if (!(error instanceof ApiError)) {
    return { form: messageForError(error) };
  }
  if (error.code === 'CURRENT_PASSWORD_INVALID') {
    return { currentPassword: t('errors.codes.CURRENT_PASSWORD_INVALID') };
  }
  if (error.code === 'PASSWORD_INVALID') {
    const issues = error.details
      .map((detail) => messageForPasswordIssue(detail.issue))
      .filter((message, index, all) => all.indexOf(message) === index);
    if (issues.length === 0) {
      return { newPassword: t('errors.codes.PASSWORD_INVALID') };
    }
    return { newPassword: issues.join(' ') };
  }
  return { form: messageForError(error) };
}

/** The support-facing request id line, or `null` when there is nothing to show. */
export function requestIdLine(error: unknown): string | null {
  if (error instanceof ApiError && error.requestId) {
    return t('errors.requestId', { requestId: error.requestId });
  }
  return null;
}
