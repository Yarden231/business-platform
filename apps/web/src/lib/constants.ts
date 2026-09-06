/**
 * Values that must stay aligned with the API.
 *
 * The API remains the source of truth: it will reject a request that slips
 * past these. They exist here so the forms can fail closed in Hebrew before
 * a round trip, and so a single file is the place to update when the policy
 * in `app/domain/passwords.py` changes.
 */
export const MIN_PASSWORD_LENGTH = 12;
export const MAX_PASSWORD_LENGTH = 256;
export const MAX_EMAIL_LENGTH = 320;

/** The HttpOnly session cookie. Readable only on the server and in `proxy.ts`. */
export const SESSION_COOKIE_NAME = 'session';

export const API_PREFIX = '/api/v1';

export const DISPLAY_LOCALE = 'he-IL';
export const DISPLAY_TIME_ZONE = 'Asia/Jerusalem';
