import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Copy, History as HistoryIcon, Search, Trash2 } from 'lucide-react';
import { api, ApiError } from '../services/api';
import type { HistoryItem, Paged } from '../types/api';
import { Badge, Button, Input } from '../components/ui/primitives';
import { Dialog } from '../components/ui/Dialog';
import { EmptyState, ErrorState, TableSkeleton } from '../components/ui/feedback';
import { useToast } from '../contexts/ToastContext';

function statusTone(status: string): 'green' | 'red' | 'amber' | 'slate' {
  if (status === 'success') return 'green';
  if (status === 'failed' || status === 'rejected') return 'red';
  if (status === 'needs_clarification') return 'amber';
  return 'slate';
}

export default function History() {
  const { push } = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<HistoryItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<HistoryItem | null>(null);

  const query = useQuery({
    queryKey: ['history', search, page],
    queryFn: () =>
      api<Paged<HistoryItem>>(
        `/api/history?page=${page}&page_size=15${search ? `&q=${encodeURIComponent(search)}` : ''}`,
      ),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api(`/api/history/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      push('History entry deleted.', 'success');
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ['history'] });
      queryClient.invalidateQueries({ queryKey: ['overview'] });
    },
    onError: (err) => push(err instanceof ApiError ? err.message : 'Delete failed.', 'error'),
  });

  const reopen = (item: HistoryItem) => {
    if (!item.generated_sql) {
      push('That entry has no SQL to reopen.', 'error');
      return;
    }
    navigate('/app/workspace', {
      state: { sql: item.generated_sql, question: item.question, connectionId: item.connection_id },
    });
  };

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Query history</h1>
        <p className="text-sm text-slate-500">
          Every generation and execution is recorded with its status. Credentials are never stored
          here.
        </p>
      </div>

      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
        <Input
          className="pl-9"
          placeholder="Search questions or SQL…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          aria-label="Search history"
        />
      </div>

      <div className="card overflow-hidden">
        {query.isLoading ? (
          <TableSkeleton rows={6} />
        ) : query.isError ? (
          <div className="p-4">
            <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
          </div>
        ) : query.data && query.data.items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title="No history yet"
              description="Generated and executed queries will be listed here."
              icon={<HistoryIcon className="h-8 w-8" />}
            />
          </div>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-900">
                <tr>
                  <th className="px-4 py-2.5">Question</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5 text-right">Rows</th>
                  <th className="px-4 py-2.5 text-right">Time</th>
                  <th className="px-4 py-2.5">When</th>
                  <th className="px-4 py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {query.data?.items.map((item) => (
                  <tr key={item.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <td className="max-w-xs truncate px-4 py-3" title={item.question}>
                      {item.question}
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={statusTone(item.execution_status)}>{item.execution_status}</Badge>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {item.row_count ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {item.execution_time_ms != null ? `${item.execution_time_ms} ms` : '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">
                      {item.created_at ? new Date(item.created_at).toLocaleString() : ''}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1.5">
                        <Button variant="ghost" onClick={() => setDetail(item)}>
                          View
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => {
                            void navigator.clipboard.writeText(item.generated_sql);
                            push('SQL copied to clipboard.', 'success');
                          }}
                          icon={<Copy className="h-4 w-4" />}
                        >
                          Copy
                        </Button>
                        <Button variant="ghost" onClick={() => setDeleteTarget(item)} icon={<Trash2 className="h-4 w-4" />}>
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-sm dark:border-slate-800">
              <span className="text-slate-500">
                {query.data?.total ?? 0} entries · page {page}
              </span>
              <div className="flex gap-2">
                <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  disabled={(query.data?.items.length ?? 0) < 15}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </div>

      <Dialog open={!!detail} title="History entry" onClose={() => setDetail(null)} wide>
        {detail && (
          <div className="space-y-3">
            <div>
              <p className="label">Question</p>
              <p className="text-sm">{detail.question}</p>
            </div>
            <div>
              <p className="label">Generated SQL</p>
              <pre className="card code-block max-h-64 overflow-y-auto p-3">{detail.generated_sql || '(none)'}</pre>
            </div>
            {detail.error_message && (
              <div>
                <p className="label">Error</p>
                <p className="text-sm text-rose-600 dark:text-rose-400">{detail.error_message}</p>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <Badge tone={statusTone(detail.execution_status)}>{detail.execution_status}</Badge>
              {detail.row_count != null && <Badge>{detail.row_count} rows</Badge>}
              {detail.execution_time_ms != null && <Badge>{detail.execution_time_ms} ms</Badge>}
            </div>
            <Button onClick={() => reopen(detail)}>Open in workspace</Button>
          </div>
        )}
      </Dialog>

      <Dialog
        open={!!deleteTarget}
        title="Delete history entry?"
        onClose={() => setDeleteTarget(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={deleteMutation.isPending}
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
            >
              Delete
            </Button>
          </>
        }
      >
        <p className="text-sm text-slate-600 dark:text-slate-400">
          This permanently removes the entry from your history.
        </p>
      </Dialog>
    </div>
  );
}
