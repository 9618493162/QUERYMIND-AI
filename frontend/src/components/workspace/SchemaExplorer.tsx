import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, RefreshCw, Search } from 'lucide-react';
import { api } from '../../services/api';
import type { DatabaseConnection, DatabaseSchema } from '../../types/api';
import { Badge, Spinner } from '../ui/primitives';
import { ErrorState } from '../ui/feedback';

export default function SchemaExplorer({ connection }: { connection: DatabaseConnection | null }) {
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const query = useQuery({
    queryKey: ['schema', connection?.id],
    queryFn: () =>
      api<DatabaseSchema>(`/api/connections/${connection!.id}/schema?refresh=true`),
    enabled: !!connection,
  });

  const filtered = useMemo(() => {
    if (!query.data) return [];
    const term = search.trim().toLowerCase();
    if (!term) return query.data.tables;
    return query.data.tables.filter(
      (t) =>
        t.name.toLowerCase().includes(term) ||
        t.schema.toLowerCase().includes(term) ||
        t.columns.some((c) => c.name.toLowerCase().includes(term)),
    );
  }, [query.data, search]);

  if (!connection) {
    return (
      <div className="p-4 text-sm text-slate-500">
        Select a database connection to explore its schema.
      </div>
    );
  }

  if (query.isLoading) {
    return (
      <div className="p-4">
        <Spinner label="Inspecting schema…" />
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="p-4">
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
          <input
            className="input py-1.5 pl-8 text-xs"
            placeholder="Search tables and columns…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search schema"
          />
        </div>
        <button
          type="button"
          aria-label="Refresh schema"
          className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
          onClick={() => query.refetch()}
        >
          <RefreshCw className={`h-4 w-4 ${query.isFetching ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {filtered.length === 0 && (
          <p className="text-sm text-slate-500">No tables or columns match “{search}”.</p>
        )}
        <ul className="space-y-1.5">
          {filtered.map((t) => {
            const key = `${t.schema}.${t.name}`;
            const open = expanded[key] ?? false;
            return (
              <li key={key}>
                <button
                  type="button"
                  className="flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
                  onClick={() => setExpanded((prev) => ({ ...prev, [key]: !open }))}
                  aria-expanded={open}
                >
                  {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                  <span className="font-mono text-xs font-medium">{t.name}</span>
                  <span className="text-xs text-slate-400">{t.schema}</span>
                  {t.kind === 'view' && <Badge tone="brand">view</Badge>}
                </button>
                {open && (
                  <ul className="ml-6 mt-1 space-y-1 border-l border-slate-200 pl-3 dark:border-slate-800">
                    {t.columns.map((c) => (
                      <li key={c.name} className="flex items-center gap-2 text-xs">
                        <span className="font-mono text-slate-700 dark:text-slate-300">{c.name}</span>
                        <span className="text-brand-600 dark:text-brand-400">{c.type}</span>
                        {c.pk && <Badge tone="brand">PK</Badge>}
                        {c.nullable === false && !c.pk && (
                          <span className="text-slate-400">not null</span>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>

        {query.data && query.data.relationships.length > 0 && (
          <div className="mt-4 border-t border-slate-200 pt-3 dark:border-slate-800">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Relationships
            </p>
            <ul className="space-y-1 text-xs text-slate-500 dark:text-slate-400">
              {query.data.relationships.map((r, i) => (
                <li key={i} className="font-mono">
                  {r.table}.{r.column} → {r.ref_table}.{r.ref_column}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
