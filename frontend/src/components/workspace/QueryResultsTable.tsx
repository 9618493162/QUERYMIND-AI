import { useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, Copy, Download, Search } from 'lucide-react';
import type { ExecuteResponse } from '../../types/api';
import { Button, Input } from '../ui/primitives';
import { EmptyState } from '../ui/feedback';
import { downloadCsv } from '../../utils/csv';

type SortState = { index: number; dir: 'asc' | 'desc' } | null;

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return 'NULL';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export default function QueryResultsTable({
  result,
  onCopyResults,
}: {
  result: ExecuteResponse;
  onCopyResults: (text: string) => void;
}) {
  const [sort, setSort] = useState<SortState>(null);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState('');
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const pageSize = 25;

  const visibleIndexes = useMemo(
    () =>
      result.columns
        .map((c, i) => ({ c, i }))
        .filter(({ c }) => !hidden.has(c.name))
        .map(({ i }) => i),
    [result.columns, hidden],
  );

  const filteredRows = useMemo(() => {
    let rows = result.rows;
    if (search.trim()) {
      const term = search.trim().toLowerCase();
      rows = rows.filter((row) =>
        row.some((cell) => cell !== null && String(cell).toLowerCase().includes(term)),
      );
    }
    if (sort) {
      const { index, dir } = sort;
      rows = [...rows].sort((a, b) => {
        const av = a[index];
        const bv = b[index];
        if (av === null) return 1;
        if (bv === null) return -1;
        if (typeof av === 'number' && typeof bv === 'number') return dir === 'asc' ? av - bv : bv - av;
        return dir === 'asc'
          ? String(av).localeCompare(String(bv))
          : String(bv).localeCompare(String(av));
      });
    }
    return rows;
  }, [result.rows, search, sort]);

  const pageCount = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const pageRows = filteredRows.slice(page * pageSize, page * pageSize + pageSize);

  const toggleSort = (index: number) => {
    setPage(0);
    setSort((prev) => {
      if (!prev || prev.index !== index) return { index, dir: 'asc' };
      if (prev.dir === 'asc') return { index, dir: 'desc' };
      return null;
    });
  };

  const copyTsv = () => {
    const header = visibleIndexes.map((i) => result.columns[i].name).join('\t');
    const body = filteredRows.map((row) => visibleIndexes.map((i) => formatCell(row[i])).join('\t'));
    onCopyResults([header, ...body].join('\n'));
  };

  if (result.rows.length === 0) {
    return (
      <EmptyState
        title="Query returned zero rows"
        description="The query executed successfully but matched no records. Try broadening the filters or date range."
      />
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
        <div className="relative min-w-40 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
          <input
            className="input py-1.5 pl-8 text-xs"
            placeholder="Search within results…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            aria-label="Search within results"
          />
        </div>
        <div className="relative">
          <select
            className="input w-auto py-1.5 pr-7 text-xs"
            aria-label="Toggle column visibility"
            value=""
            onChange={(e) => {
              const name = e.target.value;
              if (!name) return;
              setHidden((prev) => {
                const next = new Set(prev);
                if (next.has(name)) next.delete(name);
                else next.add(name);
                return next;
              });
            }}
          >
            <option value="">Columns…</option>
            {result.columns.map((c) => (
              <option key={c.name} value={c.name}>
                {hidden.has(c.name) ? '☐' : '☑'} {c.name}
              </option>
            ))}
          </select>
        </div>
        <Button variant="secondary" onClick={copyTsv} icon={<Copy className="h-4 w-4" />}>
          Copy
        </Button>
        <Button
          variant="secondary"
          onClick={() => downloadCsv(`querymind-results-${Date.now()}.csv`, visibleIndexes.map((i) => result.columns[i]), filteredRows)}
          icon={<Download className="h-4 w-4" />}
        >
          CSV
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900">
            <tr>
              {visibleIndexes.map((i) => {
                const col = result.columns[i];
                const active = sort?.index === i;
                return (
                  <th key={col.name} className="px-3 py-2 font-medium whitespace-nowrap">
                    <button
                      type="button"
                      className="flex items-center gap-1 hover:text-slate-800 dark:hover:text-slate-200"
                      onClick={() => toggleSort(i)}
                      aria-label={`Sort by ${col.name}`}
                    >
                      {col.name}
                      <span className="text-[10px] text-slate-400">{col.type}</span>
                      {active &&
                        (sort!.dir === 'asc' ? (
                          <ArrowUp className="h-3 w-3" />
                        ) : (
                          <ArrowDown className="h-3 w-3" />
                        ))}
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {pageRows.map((row, rIdx) => (
              <tr key={rIdx} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                {visibleIndexes.map((i) => {
                  const cell = row[i];
                  const isNull = cell === null || cell === undefined;
                  return (
                    <td
                      key={i}
                      className={`max-w-xs truncate px-3 py-2 ${
                        isNull ? 'italic text-slate-400' : typeof cell === 'number' ? 'tabular-nums' : ''
                      }`}
                      title={isNull ? 'NULL' : formatCell(cell)}
                    >
                      {isNull ? 'NULL' : formatCell(cell)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between border-t border-slate-200 px-3 py-2 text-xs text-slate-500 dark:border-slate-800">
        <span>
          {filteredRows.length} of {result.rows.length} rows
          {search && ` (filtered from ${result.rows.length})`}
          {result.metadata.truncated ? ' · truncated by row limit' : ''}
        </span>
        <div className="flex items-center gap-2">
          <Button variant="secondary" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            Prev
          </Button>
          <span>
            {page + 1} / {pageCount}
          </span>
          <Button
            variant="secondary"
            disabled={page + 1 >= pageCount}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
