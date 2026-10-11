/**
 * API client: fetch wrapper with CSRF double-submit, JSON handling and
 * consistent error normalization. All server communication goes through here.
 *
 * State-changing requests (POST/PATCH/DELETE) require a valid CSRF token. If
 * the CSRF cookie is missing, the client bootstraps it at most once before the
 * first mutation instead of sending the mutation without the header.
 */

import type { ApiErrorBody } from '../types/api';

/**
 * Guards the one-time CSRF bootstrap. It is set as soon as an attempt is made
 * (successful or not) so a broken backend or a cookie-less browser can never
 * cause an unbounded retry loop. `resetCsrfBootstrap()` clears it at a session
 * boundary (and a 401 does too, so an expired session can recover).
 */
let csrfBootstrapAttempted = false;

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}

export function csrfToken(): string | null {
  return readCookie('querymind_csrf');
}

type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE';

interface RequestOptions {
  method?: Method;
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const headers: Record<string, string> = {};
  if (method !== 'GET') {
    let token = csrfToken();
    if (!token) {
      // Never send a state-changing request without a CSRF token: bootstrap
      // once (which may throw `csrf_bootstrap_failed`) and re-read the cookie.
      await bootstrapCsrf();
      token = csrfToken();
    }
    if (!token) {
      throw new ApiError(
        400,
        'csrf_missing',
        'Cannot perform this action: no CSRF token could be bootstrapped. Refresh the page and try again.',
      );
    }
    headers['X-CSRF-Token'] = token;
  }

  let body: BodyInit | undefined;
  if (options.formData) {
    body = options.formData;
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body,
      credentials: 'same-origin',
      signal: options.signal,
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(0, 'network_error', 'Network error: could not reach the server.');
  }

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const data = isJson ? await response.json().catch(() => null) : null;

  if (!response.ok) {
    if (response.status === 401) {
      // Session expired or was revoked. Clear the one-time bootstrap latch so
      // the next mutation can fetch a fresh CSRF cookie instead of being stuck.
      resetCsrfBootstrap();
    }
    const errBody = data as ApiErrorBody | null;
    const message = errBody?.error?.message || `Request failed (${response.status}).`;
    const code = errBody?.error?.code || 'request_failed';
    throw new ApiError(response.status, code, message, errBody?.error?.details);
  }
  return data as T;
}

/**
 * Ensure the CSRF cookie exists before the first mutation.
 *
 * This is called automatically by `api()` for the first state-changing request
 * that lacks a CSRF cookie. It is also safe to call explicitly during app init.
 * If the bootstrap request fails it throws `csrf_bootstrap_failed` so the caller
 * can surface a real error instead of sending an unprotected mutation.
 */
export async function bootstrapCsrf(): Promise<void> {
  if (csrfToken()) {
    csrfBootstrapAttempted = true;
    return;
  }
  if (csrfBootstrapAttempted) {
    // Already tried once; do not hammer the server. An explicit reset (or a 401
    // from an expired session) starts a fresh attempt.
    return;
  }
  csrfBootstrapAttempted = true;
  try {
    const res = await fetch('/api/health', { credentials: 'same-origin' });
    if (!res.ok) {
      throw new Error(`CSRF bootstrap failed (${res.status}).`);
    }
  } catch {
    throw new ApiError(
      0,
      'csrf_bootstrap_failed',
      'Could not prepare the auth session. Reload the page and try again.',
    );
  }
}

/**
 * Reset the one-time CSRF bootstrap state, e.g. in tests or after a
 * login/logout boundary where the CSRF cookie may have changed.
 */
export function resetCsrfBootstrap() {
  csrfBootstrapAttempted = false;
}
