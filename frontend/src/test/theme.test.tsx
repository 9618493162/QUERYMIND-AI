import { describe, expect, it } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider, useTheme } from '../contexts/ThemeContext';

function Harness() {
  const { theme, resolved, toggle, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="resolved">{resolved}</span>
      <button type="button" onClick={toggle}>
        toggle
      </button>
      <button type="button" onClick={() => setTheme('dark')}>
        dark
      </button>
      <button type="button" onClick={() => setTheme('light')}>
        light
      </button>
    </div>
  );
}

describe('ThemeContext', () => {
  it('applies the dark class to the document when set to dark', async () => {
    render(
      <ThemeProvider>
        <Harness />
      </ThemeProvider>,
    );

    await userEvent.click(screen.getByRole('button', { name: 'dark' }));
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(screen.getByTestId('theme')).toHaveTextContent('dark');
    expect(screen.getByTestId('resolved')).toHaveTextContent('dark');

    await userEvent.click(screen.getByRole('button', { name: 'light' }));
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(screen.getByTestId('resolved')).toHaveTextContent('light');
  });

  it('persists the preference to localStorage', async () => {
    render(
      <ThemeProvider>
        <Harness />
      </ThemeProvider>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'dark' }));
    expect(localStorage.getItem('querymind.theme')).toBe('dark');
  });

  it('toggles between light and dark', async () => {
    render(
      <ThemeProvider>
        <Harness />
      </ThemeProvider>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'light' }));
    await userEvent.click(screen.getByRole('button', { name: 'toggle' }));
    expect(screen.getByTestId('resolved')).toHaveTextContent('dark');
    await userEvent.click(screen.getByRole('button', { name: 'toggle' }));
    expect(screen.getByTestId('resolved')).toHaveTextContent('light');
  });
});
