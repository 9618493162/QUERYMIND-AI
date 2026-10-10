import { describe, expect, it } from 'vitest';
import { rowsToCsv, sanitizeCsvCell } from '../utils/csv';
import type { ResultColumn } from '../types/api';

describe('sanitizeCsvCell (spreadsheet formula injection protection)', () => {
  it('prefixes formula-leading values with a single quote', () => {
    expect(sanitizeCsvCell('=1+1')).toBe("'=1+1");
    expect(sanitizeCsvCell('=cmd|\' /c calc\'!A1')).toContain("'=cmd");
    expect(sanitizeCsvCell('+SUM(A1)')).toBe("'+SUM(A1)");
    expect(sanitizeCsvCell('-2+3')).toBe("'-2+3");
    expect(sanitizeCsvCell('@import')).toBe("'@import");
    expect(sanitizeCsvCell('\tTAB')).toBe("'\tTAB");
  });

  it('passes ordinary values through unchanged', () => {
    expect(sanitizeCsvCell('North')).toBe('North');
    expect(sanitizeCsvCell(42)).toBe('42');
    expect(sanitizeCsvCell(3.14)).toBe('3.14');
    expect(sanitizeCsvCell(null)).toBe('');
    expect(sanitizeCsvCell(undefined)).toBe('');
    expect(sanitizeCsvCell(false)).toBe('false');
  });

  it('quotes values containing commas, quotes or newlines', () => {
    expect(sanitizeCsvCell('a,b')).toBe('"a,b"');
    expect(sanitizeCsvCell('say "hi"')).toBe('"say ""hi"""');
    expect(sanitizeCsvCell('line1\nline2')).toBe('"line1\nline2"');
  });
});

describe('rowsToCsv', () => {
  const columns: ResultColumn[] = [
    { name: 'name', type: 'string' },
    { name: 'total', type: 'number' },
  ];

  it('serializes header and rows', () => {
    const csv = rowsToCsv(columns, [
      ['Alice', 100],
      ['Bob', null],
    ]);
    const lines = csv.split('\r\n');
    expect(lines[0]).toBe('name,total');
    expect(lines[1]).toBe('Alice,100');
    expect(lines[2]).toBe('Bob,');
  });

  it('neutralizes formula payloads in data cells', () => {
    const csv = rowsToCsv(columns, [['=HYPERLINK("http://evil")', 1]]);
    const line = csv.split('\r\n')[1];
    expect(line).not.toMatch(/^=/);
    expect(line).toContain("'=HYPERLINK");
  });
});
