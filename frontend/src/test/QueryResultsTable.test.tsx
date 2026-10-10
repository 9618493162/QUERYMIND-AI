import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import QueryResultsTable from '../components/workspace/QueryResultsTable';
import type { ExecuteResponse } from '../types/api';

const result: ExecuteResponse = {
  success: true,
  columns: [
    { name: 'status', type: 'string' },
    { name: 'cnt', type: 'number' },
  ],
  rows: [
    ['completed', 17],
    ['cancelled', 3],
    [null, 4],
  ],
  metadata: { row_count: 3, returned_rows: 3, execution_time_ms: 12, truncated: false, response_bytes: 512 },
  chart: { type: 'bar', x: 'status', y: 'cnt', available: true, reason: 'categories' },
  history_id: 'h1',
};

describe('QueryResultsTable', () => {
  it('renders rows including explicit NULL markers', () => {
    render(<QueryResultsTable result={result} onCopyResults={vi.fn()} />);
    expect(screen.getByText('completed')).toBeInTheDocument();
    expect(screen.getByText('cancelled')).toBeInTheDocument();
    expect(screen.getAllByText('NULL')).toHaveLength(1);
  });

  it('shows an empty state when the query returns zero rows', () => {
    render(
      <QueryResultsTable result={{ ...result, rows: [], metadata: { ...result.metadata, row_count: 0, returned_rows: 0 } }} onCopyResults={vi.fn()} />,
    );
    expect(screen.getByText(/zero rows/i)).toBeInTheDocument();
  });

  it('sorts numerically when a column header is clicked', async () => {
    render(<QueryResultsTable result={result} onCopyResults={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /sort by cnt/i }));
    const cells = screen.getAllByRole('cell').map((c) => c.textContent);
    // ascending: 3 before 4 before 17
    expect(cells).toContain('3');
    expect(cells.indexOf('3')).toBeLessThan(cells.indexOf('17'));
  });

  it('filters rows by the results search box', async () => {
    render(<QueryResultsTable result={result} onCopyResults={vi.fn()} />);
    await userEvent.type(screen.getByLabelText(/search within results/i), 'cancel');
    expect(screen.getByText('cancelled')).toBeInTheDocument();
    expect(screen.queryByText('completed')).not.toBeInTheDocument();
  });

  it('copies visible results as TSV', async () => {
    const onCopy = vi.fn();
    render(<QueryResultsTable result={result} onCopyResults={onCopy} />);
    await userEvent.click(screen.getByRole('button', { name: /copy/i }));
    expect(onCopy).toHaveBeenCalledTimes(1);
    const text = onCopy.mock.calls[0][0] as string;
    expect(text.split('\n')[0]).toBe('status\tcnt');
    expect(text).toContain('completed\t17');
  });

  it('shows truncation notice from metadata', () => {
    render(
      <QueryResultsTable
        result={{ ...result, metadata: { ...result.metadata, truncated: true } }}
        onCopyResults={vi.fn()}
      />,
    );
    expect(screen.getByText(/truncated/i)).toBeInTheDocument();
  });
});
