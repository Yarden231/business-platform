/**
 * The typed failure model for API calls (docs/api.md §2).
 *
 * Every non-2xx response carries the same envelope, so it is parsed once, here,
 * into an `ApiError` whose `code` the Hebrew mapper consumes. Feature code
 * never reads `error.message` — that field is English and developer-facing
 * (ADR-0014).
 */
import type { ErrorCode, ErrorDetail } from '@/lib/api/types';

/** A response the API produced: it has a status, a stable code and a request id. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode;
  readonly details: readonly ErrorDetail[];
  /** `null` only when the response did not come from the API itself. */
  readonly requestId: string | null;

  constructor(init: {
    status: number;
    code: ErrorCode;
    message: string;
    details: readonly ErrorDetail[];
    requestId: string | null;
  }) {
    super(init.message);
    this.name = 'ApiError';
    this.status = init.status;
    this.code = init.code;
    this.details = init.details;
    this.requestId = init.requestId;
  }
}

/**
 * The request never produced a response — offline, DNS failure, the proxy
 * refusing the connection. Distinct from `ApiError` because there is no code
 * and no request id to show, so the Hebrew copy has to differ.
 */
export class NetworkError extends Error {
  constructor(cause?: unknown) {
    super('The API could not be reached.');
    this.name = 'NetworkError';
    this.cause = cause;
  }
}

/**
 * The code to assume when a non-2xx response is *not* an API error envelope.
 *
 * This is not paranoia about the API: the browser talks to the Next.js origin,
 * so a proxy that cannot reach the API answers with its own `502`/`504` and an
 * HTML body. Mapping the status keeps the UI showing accurate Hebrew instead of
 * a generic failure.
 */
function codeForStatus(status: number): ErrorCode {
  switch (status) {
    case 400:
      return 'BAD_REQUEST';
    case 401:
      return 'AUTH_REQUIRED';
    case 403:
      return 'FORBIDDEN';
    case 404:
      return 'NOT_FOUND';
    case 405:
      return 'METHOD_NOT_ALLOWED';
    case 409:
      return 'CONFLICT';
    case 422:
      return 'VALIDATION_ERROR';
    case 429:
      return 'TOO_MANY_REQUESTS';
    case 502:
    case 503:
    case 504:
      return 'SERVICE_UNAVAILABLE';
    default:
      return 'INTERNAL_ERROR';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function parseDetails(value: unknown): readonly ErrorDetail[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((entry: unknown) => {
    if (!isRecord(entry) || typeof entry.issue !== 'string') {
      return [];
    }
    return [{ issue: entry.issue, field: typeof entry.field === 'string' ? entry.field : null }];
  });
}

/**
 * Build an `ApiError` from a failed response.
 *
 * The body is read defensively rather than cast: it may be the envelope, an
 * HTML page from the proxy, or empty. `code` is only trusted when it is a
 * string, and it is not checked against the `ErrorCode` union at runtime — the
 * generated types make the API side of that agreement a build-time concern, and
 * an unmapped code still renders correct Hebrew through the mapper's fallback.
 */
export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  const requestId = response.headers.get('X-Request-ID');
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const body = isRecord(payload) && isRecord(payload.error) ? payload.error : null;
  const code =
    body !== null && typeof body.code === 'string'
      ? (body.code as ErrorCode)
      : codeForStatus(response.status);

  return new ApiError({
    status: response.status,
    code,
    message:
      body !== null && typeof body.message === 'string'
        ? body.message
        : `Request failed with status ${response.status}.`,
    details: body === null ? [] : parseDetails(body.details),
    requestId: body !== null && typeof body.request_id === 'string' ? body.request_id : requestId,
  });
}
