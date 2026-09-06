/**
 * Named aliases over the generated OpenAPI types.
 *
 * `schema.d.ts` is generated from the API's own OpenAPI document and committed;
 * `./scripts/check` fails if it is stale (ADR-0017). Nothing outside this file
 * reaches into `components['schemas'][...]`, so a renamed schema is fixed in
 * one place, and no request or response shape is ever hand-written.
 */
import type { components } from '@/lib/api/schema';

type Schemas = components['schemas'];

/** `GET /api/v1/auth/me`. The only five fields the API discloses about a session. */
export type CurrentUser = Schemas['CurrentUserResponse'];

export type UserRole = Schemas['UserRole'];

export type LoginBody = Schemas['LoginRequest'];

export type PasswordChangeBody = Schemas['PasswordChangeRequest'];

/** Every stable error code the API can return. Exhaustive by generation. */
export type ErrorCode = Schemas['ErrorCode'];

export type ErrorDetail = Schemas['ErrorDetailModel'];

export type ErrorEnvelope = Schemas['ErrorEnvelope'];

/**
 * The password-policy violations the API reports as `details[].issue` alongside
 * `PASSWORD_INVALID`.
 *
 * Not generated, because `issue` is an open `string` in the contract: the same
 * field also carries Pydantic's own validation types (`string_too_short`, …)
 * from a different layer, so it cannot be a closed enum in OpenAPI. This union
 * mirrors `PasswordIssue` in `apps/api/app/domain/passwords.py`, and the mapper
 * falls back to the generic `PASSWORD_INVALID` message for anything it does not
 * recognise — so an unmirrored issue degrades to a correct general message
 * instead of showing the caller a raw code.
 */
export type PasswordIssue =
  'too_short' | 'too_long' | 'common' | 'whitespace_only' | 'same_as_current';
