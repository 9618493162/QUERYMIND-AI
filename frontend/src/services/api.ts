/**
 * API client: fetch wrapper with CSRF double-submit, JSON handling and
 * consistent error normalization. All server communication goes through here.
 */

import type { ApiErrorBody } from '../types/api';

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
    const token = csrfToken();
    if (token) headers['X-CSRF-Token'] = token;
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
    const errBody = data as ApiErrorBody | null;
    const message = errBody?.error?.message || `Request failed (${response.status}).`;
    const code = errBody?.error?.code || 'request_failed';
    throw new ApiError(response.status, code, message, errBody?.error?.details);
  }
  return data as T;
}

/** Ensure the CSRF cookie exists before the first mutation. */
export async function bootstrapCsrf(): Promise<void> {
  if (!csrfToken()) {
    await fetch('/api/health', { credentials: 'same-origin' }).catch(() => undefined);
  }
}
