import type { ResultColumn } from '../types/api';

/**
 * CSV export with spreadsheet formula-injection protection.
 * Values starting with =, +, -, @, tab or CR are prefixed with a single quote
 * so Excel/Sheets treat them as text instead of executing them.
 */
export function sanitizeCsvCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  let str = typeof value === 'string' ? value : String(value);
  if (/^[=+\-@\t\r]/.test(str)) {
    str = `'${str}`;
  }
  if (/[",\n\r]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

export function rowsToCsv(columns: ResultColumn[], rows: (string | number | boolean | null)[][]): string {
  const header = columns.map((c) => sanitizeCsvCell(c.name)).join(',');
  const body = rows.map((row) => row.map(sanitizeCsvCell).join(','));
  return [header, ...body].join('\r\n');
}

export function downloadCsv(filename: string, columns: ResultColumn[], rows: (string | number | boolean | null)[][]) {
  const csv = rowsToCsv(columns, rows);
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename.endsWith('.csv') ? filename : `${filename}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
