import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import Login from '../pages/Login';
import { AuthProvider } from '../contexts/AuthContext';
import { ToastProvider } from '../contexts/ToastContext';

function renderLogin() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <AuthProvider>
          <Login />
        </AuthProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

describe('Login page', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes('/api/health')) {
          return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
        }
        if (url.includes('/api/auth/me')) {
          return new Response('{"success":false}', { status: 401, headers: { 'content-type': 'application/json' } });
        }
        if (url.includes('/api/auth/login')) {
          const body = JSON.parse(String(init?.body));
          if (body.password === 'Sup3rSecret!') {
            return new Response(
              JSON.stringify({ success: true, user: { id: '1', name: 'Dev', email: body.email } }),
              { status: 200, headers: { 'content-type': 'application/json' } },
            );
          }
          return new Response(
            JSON.stringify({ success: false, error: { code: 'invalid_credentials', message: 'Incorrect email or password.' } }),
            { status: 401, headers: { 'content-type': 'application/json' } },
          );
        }
        return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } });
      }),
    );
    document.cookie = 'querymind_csrf=test-token';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the sign-in form', () => {
    renderLogin();
    expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it('shows a validation error for an invalid email and does not submit', async () => {
    renderLogin();
    await userEvent.type(screen.getByLabelText(/email/i), 'not-an-email');
    await userEvent.type(screen.getByLabelText(/password/i), 'whatever123');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/valid email/i)).toBeInTheDocument();
    });
    expect(fetch).not.toHaveBeenCalledWith('/api/auth/login', expect.anything());
  });

  it('submits valid credentials', async () => {
    renderLogin();
    await userEvent.type(screen.getByLabelText(/email/i), 'dev@querymind.dev');
    await userEvent.type(screen.getByLabelText(/password/i), 'Sup3rSecret!');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        '/api/auth/login',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('surfaces server-side authentication errors', async () => {
    renderLogin();
    await userEvent.type(screen.getByLabelText(/email/i), 'dev@querymind.dev');
    await userEvent.type(screen.getByLabelText(/password/i), 'wrong-password');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/incorrect email or password/i);
    });
  });
});
