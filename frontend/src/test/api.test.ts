import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  api,
  bootstrapCsrf,
  csrfToken,
  resetCsrfBootstrap,
} from '../services/api';

function clearCookies() {
  document.cookie = 'querymind_csrf=; Max-Age=0; path=/';
  document.cookie = 'querymind_session=; Max-Age=0; path=/';
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

/** Await a promise that must reject and return the typed error instance. */
async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (e) {
    return e as ApiError;
  }
  throw new Error('Expected the request to reject, but it resolved.');
}

describe('api CSRF bootstrap hardening', () => {
  beforeEach(() => {
    clearCookies();
    resetCsrfBootstrap();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends an existing CSRF token on a mutation without re-bootstrapping', async () => {
    document.cookie = 'querymind_csrf=existing-token; path=/';
    const fetchFn = vi.fn(async () => jsonResponse({ success: true }));
    vi.stubGlobal('fetch', fetchFn);

    await api('/api/auth/logout', { method: 'POST' });

    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(fetchFn).toHaveBeenCalledWith(
      '/api/auth/logout',
      expect.objectContaining({
        method: 'POST',
        credentials: 'same-origin',
        headers: expect.objectContaining({ 'X-CSRF-Token': 'existing-token' }),
      }),
    );
  });

  it('bootstraps a missing CSRF cookie before the first mutation', async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/health') {
        document.cookie = 'querymind_csrf=token-after-bootstrap; path=/';
      }
      return jsonResponse({ success: true });
    });
    vi.stubGlobal('fetch', fetchFn);

    await api('/api/auth/logout', { method: 'POST' });

    expect(fetchFn).toHaveBeenCalledTimes(2);
    expect(fetchFn).toHaveBeenNthCalledWith(
      1,
      '/api/health',
      expect.objectContaining({ credentials: 'same-origin' }),
    );
    expect(fetchFn).toHaveBeenNthCalledWith(
      2,
      '/api/auth/logout',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'X-CSRF-Token': 'token-after-bootstrap' }),
      }),
    );
  });

  it('rejects a mutation when the bootstrap request fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({}, 500)));

    const error = await rejection(api('/api/auth/logout', { method: 'POST' }));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe('csrf_bootstrap_failed');
  });

  it('rejects (and never sends) a mutation when bootstrap sets no cookie', async () => {
    const fetchFn = vi.fn(async () => jsonResponse({ success: true }));
    vi.stubGlobal('fetch', fetchFn);

    const error = await rejection(api('/api/auth/logout', { method: 'POST' }));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe('csrf_missing');
    // Only the bootstrap call happened; the unsafe mutation was never sent.
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(fetchFn).toHaveBeenCalledWith('/api/health', expect.anything());
  });

  it('does not retry the bootstrap on repeated mutations (no infinite loop)', async () => {
    const fetchFn = vi.fn(async () => jsonResponse({ success: true }));
    vi.stubGlobal('fetch', fetchFn);

    await expect(api('/api/auth/logout', { method: 'POST' })).rejects.toThrow(/no CSRF token/i);
    await expect(api('/api/auth/logout', { method: 'POST' })).rejects.toThrow(/no CSRF token/i);

    expect(fetchFn).toHaveBeenCalledTimes(1); // exactly one bootstrap attempt
  });

  it('allows safe reads with no CSRF token and never bootstraps', async () => {
    const fetchFn = vi.fn(async () => jsonResponse({ success: true }));
    vi.stubGlobal('fetch', fetchFn);

    await api('/api/health');

    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(fetchFn).toHaveBeenCalledWith(
      '/api/health',
      expect.objectContaining({ credentials: 'same-origin' }),
    );
    expect(csrfToken()).toBeNull();
  });

  it('recovers after an expired session by re-bootstrapping a fresh token', async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === '/api/health') {
        document.cookie = 'querymind_csrf=recovered-token; path=/';
        return jsonResponse({ success: true });
      }
      // Simulate the CSRF cookie expiring together with the session.
      document.cookie = 'querymind_csrf=; Max-Age=0; path=/';
      return jsonResponse(
        { success: false, error: { code: 'unauthorized', message: 'Session expired.' } },
        401,
      );
    });
    vi.stubGlobal('fetch', fetchFn);

    document.cookie = 'querymind_csrf=stale-token; path=/';
    await expect(api('/api/auth/logout', { method: 'POST' })).rejects.toThrow(/Session expired/);
    expect(csrfToken()).toBeNull();

    await expect(api('/api/auth/logout', { method: 'POST' })).rejects.toThrow(/Session expired/);
    expect(fetchFn).toHaveBeenCalledWith('/api/health', expect.anything());
  });

  it('resetCsrfBootstrap allows an explicit fresh attempt after a failed one', async () => {
    const first = vi.fn(async () => jsonResponse({ success: true })); // no cookie set
    vi.stubGlobal('fetch', first);

    await bootstrapCsrf();
    expect(first).toHaveBeenCalledTimes(1);
    expect(csrfToken()).toBeNull();

    // Latched: a second call must not hit the network again.
    await bootstrapCsrf();
    expect(first).toHaveBeenCalledTimes(1);

    resetCsrfBootstrap();
    const second = vi.fn(async () => {
      document.cookie = 'querymind_csrf=fresh; path=/';
      return jsonResponse({ success: true });
    });
    vi.stubGlobal('fetch', second);

    await bootstrapCsrf();
    expect(csrfToken()).toBe('fresh');
    expect(second).toHaveBeenCalledTimes(1);
  });
});
