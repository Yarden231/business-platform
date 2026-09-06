import { describe, expect, it } from 'vitest';

import { ApiError, NetworkError } from '@/lib/api/errors';
import { he } from '@/messages/he';
import {
  fieldMessagesForPasswordError,
  messageForError,
  messageForPasswordIssue,
  requestIdLine,
} from '@/messages/errors';
import { t } from '@/messages/t';

describe('messageForError', () => {
  it('maps a network failure to the network copy', () => {
    expect(messageForError(new NetworkError())).toBe(t('errors.network'));
  });

  it('maps an API code through the catalog', () => {
    expect(
      messageForError(
        new ApiError({
          status: 401,
          code: 'AUTH_INVALID_CREDENTIALS',
          message: 'Those credentials are not valid.',
          details: [],
          requestId: 'r',
        }),
      ),
    ).toBe(he.errors.codes.AUTH_INVALID_CREDENTIALS);
  });

  it('falls back for an unknown exception', () => {
    expect(messageForError(new Error('boom'))).toBe(t('errors.unexpected'));
  });
});

describe('messageForPasswordIssue', () => {
  it('fills in the policy bounds', () => {
    expect(messageForPasswordIssue('too_short')).toBe(
      t('errors.passwordIssues.too_short', { min: 12 }),
    );
  });

  it('falls back for an unrecognised issue', () => {
    expect(messageForPasswordIssue('string_too_short')).toBe(t('errors.codes.PASSWORD_INVALID'));
  });
});

describe('fieldMessagesForPasswordError', () => {
  it('attaches CURRENT_PASSWORD_INVALID to the current-password field', () => {
    expect(
      fieldMessagesForPasswordError(
        new ApiError({
          status: 422,
          code: 'CURRENT_PASSWORD_INVALID',
          message: 'The current password is not correct.',
          details: [],
          requestId: 'r',
        }),
      ),
    ).toEqual({ currentPassword: t('errors.codes.CURRENT_PASSWORD_INVALID') });
  });

  it('attaches PASSWORD_INVALID details to the new-password field', () => {
    const mapped = fieldMessagesForPasswordError(
      new ApiError({
        status: 422,
        code: 'PASSWORD_INVALID',
        message: 'The password does not meet the password policy.',
        details: [{ field: 'new_password', issue: 'too_short' }],
        requestId: 'r',
      }),
    );
    expect(mapped.newPassword).toBe(t('errors.passwordIssues.too_short', { min: 12 }));
  });
});

describe('requestIdLine', () => {
  it('returns null when there is no request id', () => {
    expect(requestIdLine(new NetworkError())).toBeNull();
  });

  it('formats a request id from an ApiError', () => {
    expect(
      requestIdLine(
        new ApiError({
          status: 500,
          code: 'INTERNAL_ERROR',
          message: 'An unexpected error occurred.',
          details: [],
          requestId: 'abc-123',
        }),
      ),
    ).toBe(t('errors.requestId', { requestId: 'abc-123' }));
  });
});
