import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Copy, Pencil, Play, Save, Search, Star, Trash2 } from 'lucide-react';
import { api, ApiError } from '../services/api';
import type { Paged, SavedQuery } from '../types/api';
import { Badge, Button, Field, Input } from '../components/ui/primitives';
import { Dialog } from '../components/ui/Dialog';
import { EmptyState, ErrorState, TableSkeleton } from '../components/ui/feedback';
import { useToast } from '../contexts/ToastContext';

export default function SavedQueries() {
  const { push } = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<SavedQuery | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SavedQuery | null>(null);
  const [form, setForm] = useState({ title: '', description: '', tags: '' });

  const query = useQuery({
    queryKey: ['saved', search],
    queryFn: () =>
      api<Paged<SavedQuery>>(
        `/api/saved-queries?page_size=50${search ? `&q=${encodeURIComponent(search)}` : ''}`,
      ),
  });

  const patchMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<SavedQuery> }) =>
      api(`/api/saved-queries/${id}`, { method: 'PATCH', body }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved'] });
      queryClient.invalidateQueries({ queryKey: ['overview'] });
    },
    onError: (err) => push(err instanceof ApiError ? err.message : 'Update failed.', 'error'),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api(`/api/saved-queries/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      push('Saved query deleted.', 'success');
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ['saved'] });
      queryClient.invalidateQueries({ queryKey: ['overview'] });
    },
    onError: (err) => push(err instanceof ApiError ? err.message : 'Delete failed.', 'error'),
  });

  const openEdit = (item: SavedQuery) => {
    setEditing(item);
    setForm({
      title: item.title,
      description: item.description ?? '',
      tags: item.tags.join(', '),
    });
  };

  const saveEdit = () => {
    if (!editing) return;
    patchMutation.mutate(
      {
        id: editing.id,
        body: {
          title: form.title,
          description: form.description || null,
          tags: form.tags
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean),
        },
      },
      { onSuccess: () => setEditing(null) },
    );
  };

  const runQuery = (item: SavedQuery) => {
    if (!item.connection_id) {
      push('This saved query is not linked to a connection anymore.', 'error');
      return;
    }
    navigate('/app/workspace', {
      state: {
        sql: item.sql_query,
        question: item.natural_language_question || item.title,
        connectionId: item.connection_id,
        autoExecute: true,
      },
    });
  };

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Saved queries</h1>
        <p className="text-sm text-slate-500">
          Reopen or re-run useful queries. Re-running always revalidates the SQL first.
        </p>
      </div>

      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
        <Input
          className="pl-9"
          placeholder="Search saved queries…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search saved queries"
        />
      </div>

      <div className="card overflow-hidden">
        {query.isLoading ? (
          <TableSkeleton rows={5} />
        ) : query.isError ? (
          <div className="p-4">
            <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
          </div>
        ) : query.data && query.data.items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title="No saved queries"
              description="Save a query from the workspace to reuse it later."
              icon={<Save className="h-8 w-8" />}
            />
          </div>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {query.data?.items.map((item) => (
              <li key={item.id} className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      aria-label={item.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
                      onClick={() => patchMutation.mutate({ id: item.id, body: { is_favorite: !item.is_favorite } })}
                      className={item.is_favorite ? 'text-amber-500' : 'text-slate-300 hover:text-amber-500 dark:text-slate-600'}
                    >
                      <Star className="h-4 w-4" fill={item.is_favorite ? 'currentColor' : 'none'} />
                    </button>
                    <p className="truncate font-medium">{item.title}</p>
                    {item.tags.map((t) => (
                      <Badge key={t}>{t}</Badge>
                    ))}
                  </div>
                  {item.description && (
                    <p className="mt-1 truncate text-sm text-slate-500">{item.description}</p>
                  )}
                  <pre className="code-block mt-1 max-h-10 overflow-hidden text-slate-400">{item.sql_query}</pre>
                </div>
                <div className="flex shrink-0 gap-1.5">
                  <Button variant="secondary" onClick={() => runQuery(item)} icon={<Play className="h-4 w-4" />}>
                    Run
                  </Button>
                  <Button variant="secondary" onClick={() => openEdit(item)} icon={<Pencil className="h-4 w-4" />}>
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      void navigator.clipboard.writeText(item.sql_query);
                      push('SQL copied.', 'success');
                    }}
                    icon={<Copy className="h-4 w-4" />}
                  />
                  <Button variant="ghost" onClick={() => setDeleteTarget(item)} icon={<Trash2 className="h-4 w-4" />} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Dialog
        open={!!editing}
        title="Edit saved query"
        onClose={() => setEditing(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button loading={patchMutation.isPending} onClick={saveEdit}>
              Save changes
            </Button>
          </>
        }
      >
        <Field label="Title">
          <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </Field>
        <Field label="Description">
          <Input
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="What does this query answer?"
          />
        </Field>
        <Field label="Tags" hint="Comma separated">
          <Input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
        </Field>
      </Dialog>

      <Dialog
        open={!!deleteTarget}
        title="Delete saved query?"
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
        <p className="text-sm text-slate-600 dark:text-slate-400">“{deleteTarget?.title}” will be removed permanently.</p>
      </Dialog>
    </div>
  );
}
