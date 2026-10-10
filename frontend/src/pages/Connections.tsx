import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  CheckCircle2,
  Database,
  Loader2,
  Pencil,
  Plug,
  Plus,
  RefreshCw,
  Trash2,
  XCircle,
} from 'lucide-react';
import { api, ApiError } from '../services/api';
import type { DatabaseConnection, DatabaseSchema, TestResult } from '../types/api';
import { Badge, Button, Field, Input } from '../components/ui/primitives';
import { Dialog } from '../components/ui/Dialog';
import { EmptyState, ErrorState, Skeleton } from '../components/ui/feedback';
import { useToast } from '../contexts/ToastContext';

const connectionSchema = z.object({
  name: z.string().min(1, 'Name is required').max(120),
  host: z.string().min(1, 'Host is required').max(255),
  port: z.coerce.number().int().min(1).max(65535),
  database_name: z.string().min(1, 'Database name is required').max(255),
  username: z.string().min(1, 'Username is required').max(255),
  password: z.string().max(512),
  ssl_mode: z.enum(['disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full']),
});

type FormValues = z.infer<typeof connectionSchema>;

const DEFAULT_VALUES: FormValues = {
  name: '',
  host: 'localhost',
  port: 5433,
  database_name: 'analytics',
  username: 'analytics_owner',
  password: '',
  ssl_mode: 'prefer',
};

export default function Connections() {
  const queryClient = useQueryClient();
  const { push } = useToast();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<DatabaseConnection | null>(null);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DatabaseConnection | null>(null);
  const [schemaTarget, setSchemaTarget] = useState<DatabaseConnection | null>(null);

  const list = useQuery({
    queryKey: ['connections'],
    queryFn: () => api<{ success: boolean; items: DatabaseConnection[] }>('/api/connections'),
  });

  const form = useForm<FormValues>({
    resolver: zodResolver(connectionSchema),
    defaultValues: DEFAULT_VALUES,
  });

  const saveMutation = useMutation({
    mutationFn: (values: FormValues) =>
      api<{ success: boolean; connection: DatabaseConnection }>('/api/connections', {
        method: 'POST',
        body: values,
      }),
    onSuccess: () => {
      push('Connection saved.', 'success');
      setFormOpen(false);
      form.reset(DEFAULT_VALUES);
      setEditing(null);
      queryClient.invalidateQueries({ queryKey: ['connections'] });
      queryClient.invalidateQueries({ queryKey: ['overview'] });
    },
    onError: (err) => push(err instanceof ApiError ? err.message : 'Failed to save connection.', 'error'),
  });

  const testMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      api<TestResult>('/api/connections/test', {
        method: 'POST',
        body: { ...values, database_type: 'postgresql' },
      }),
    onSuccess: (result) => setTestResult(result),
    onError: (err) =>
      setTestResult({
        success: false,
        message: err instanceof ApiError ? err.message : 'Test failed.',
        server_version: null,
        latency_ms: null,
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api(`/api/connections/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      push('Connection deleted.', 'success');
      setDeleteTarget(null);
      queryClient.invalidateQueries({ queryKey: ['connections'] });
      queryClient.invalidateQueries({ queryKey: ['overview'] });
    },
    onError: (err) => push(err instanceof ApiError ? err.message : 'Delete failed.', 'error'),
  });

  const onSubmit = (values: FormValues) => saveMutation.mutate(values);

  const openCreate = () => {
    setEditing(null);
    form.reset(DEFAULT_VALUES);
    setTestResult(null);
    setFormOpen(true);
  };

  const openEdit = (conn: DatabaseConnection) => {
    setEditing(conn);
    form.reset({
      name: conn.name,
      host: conn.host,
      port: conn.port,
      database_name: conn.database_name,
      username: conn.username,
      password: '',
      ssl_mode: conn.ssl_mode as FormValues['ssl_mode'],
    });
    setTestResult(null);
    setFormOpen(true);
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold">Database connections</h1>
          <p className="text-sm text-slate-500">
            Connect authorized PostgreSQL databases. Passwords are encrypted at rest and never sent
            back to the browser.
          </p>
        </div>
        <Button onClick={openCreate} icon={<Plus className="h-4 w-4" />}>
          New connection
        </Button>
      </div>

      {list.isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      )}

      {list.isError && (
        <ErrorState message={(list.error as Error).message} onRetry={() => list.refetch()} />
      )}

      {list.data && list.data.items.length === 0 && (
        <EmptyState
          title="No connections yet"
          description="Add a PostgreSQL connection to inspect its schema and start asking questions against real data."
          action={
            <Button onClick={openCreate} icon={<Plus className="h-4 w-4" />}>
              Add your first connection
            </Button>
          }
        />
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {list.data?.items.map((conn) => (
          <div key={conn.id} className="card p-4">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-100 text-brand-700 dark:bg-brand-900/50 dark:text-brand-300">
                  <Database className="h-4 w-4" />
                </span>
                <div>
                  <p className="font-semibold">{conn.name}</p>
                  <p className="text-xs text-slate-500">
                    {conn.username}@{conn.host}:{conn.port}/{conn.database_name}
                  </p>
                </div>
              </div>
              <Badge tone={conn.ssl_mode.includes('verify') || conn.ssl_mode === 'require' ? 'green' : 'amber'}>
                {conn.ssl_mode}
              </Badge>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                variant="secondary"
                loading={testMutation.isPending && testMutation.variables?.host === conn.host}
                onClick={() =>
                  testMutation.mutate({
                    name: conn.name,
                    host: conn.host,
                    port: conn.port,
                    database_name: conn.database_name,
                    username: conn.username,
                    password: '',
                    ssl_mode: conn.ssl_mode,
                  } as Record<string, unknown>)
                }
                icon={<Plug className="h-4 w-4" />}
              >
                Test
              </Button>
              <Button
                variant="secondary"
                onClick={() => setSchemaTarget(conn)}
                icon={<RefreshCw className="h-4 w-4" />}
              >
                Schema
              </Button>
              <Button variant="secondary" onClick={() => openEdit(conn)} icon={<Pencil className="h-4 w-4" />}>
                Edit
              </Button>
              <Button variant="danger" onClick={() => setDeleteTarget(conn)} icon={<Trash2 className="h-4 w-4" />}>
                Delete
              </Button>
            </div>

            {testMutation.isPending && testMutation.variables?.host === conn.host && (
              <p className="mt-3 text-sm text-slate-500">Testing connection…</p>
            )}
            {testResult && testMutation.variables?.host === conn.host && !testMutation.isPending && (
              <div
                className={`mt-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${
                  testResult.success
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'
                    : 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300'
                }`}
              >
                {testResult.success ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                ) : (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
                )}
                <span>
                  {testResult.message}
                  {testResult.server_version && ` (PostgreSQL ${testResult.server_version})`}
                  {testResult.latency_ms != null && ` · ${testResult.latency_ms} ms`}
                  {!testResult.success && conn.has_password === false && (
                    <> Save the connection with a password to test authenticated access.</>
                  )}
                </span>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Create / edit dialog */}
      <Dialog
        open={formOpen}
        title={editing ? `Edit ${editing.name}` : 'New database connection'}
        onClose={() => setFormOpen(false)}
        wide
        footer={
          <>
            <Button variant="secondary" onClick={() => setFormOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              loading={testMutation.isPending}
              icon={<Plug className="h-4 w-4" />}
              onClick={() => {
                const parsed = connectionSchema.safeParse(form.getValues());
                if (!parsed.success) {
                  void form.trigger();
                  return;
                }
                testMutation.mutate(parsed.data);
              }}
            >
              Test
            </Button>
            <Button form="connection-form" type="submit" loading={saveMutation.isPending}>
              Save connection
            </Button>
          </>
        }
      >
        <form id="connection-form" onSubmit={form.handleSubmit(onSubmit)} noValidate>
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label="Connection name" error={form.formState.errors.name?.message}>
              <Input placeholder="Production analytics" {...form.register('name')} />
            </Field>
            <Field label="SSL mode" error={form.formState.errors.ssl_mode?.message}>
              <select className="input" {...form.register('ssl_mode')}>
                <option value="disable">disable</option>
                <option value="allow">allow</option>
                <option value="prefer">prefer</option>
                <option value="require">require</option>
                <option value="verify-ca">verify-ca</option>
                <option value="verify-full">verify-full</option>
              </select>
            </Field>
            <Field label="Host" error={form.formState.errors.host?.message}>
              <Input placeholder="localhost" {...form.register('host')} />
            </Field>
            <Field label="Port" error={form.formState.errors.port?.message}>
              <Input type="number" {...form.register('port')} />
            </Field>
            <Field label="Database name" error={form.formState.errors.database_name?.message}>
              <Input placeholder="analytics" {...form.register('database_name')} />
            </Field>
            <Field label="Username" error={form.formState.errors.username?.message}>
              <Input autoComplete="username" {...form.register('username')} />
            </Field>
            <Field
              label="Password"
              error={form.formState.errors.password?.message}
              hint={editing ? 'Leave blank to keep the stored password.' : 'Stored encrypted; never returned to the client.'}
            >
              <Input type="password" autoComplete="new-password" {...form.register('password')} />
            </Field>
          </div>

          <div className="mt-2 flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
            <Plug className="h-3.5 w-3.5 shrink-0" />
            Use the buttons below to test connectivity before saving.
          </div>
        </form>

        {testResult && (
          <div
            className={`mt-3 rounded-lg border px-3 py-2 text-sm ${
              testResult.success
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'
                : 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300'
            }`}
          >
            {testResult.message}
            {testResult.server_version && ` (PostgreSQL ${testResult.server_version})`}
          </div>
        )}
      </Dialog>

      {/* Delete confirmation */}
      <Dialog
        open={!!deleteTarget}
        title="Delete connection?"
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
          “{deleteTarget?.name}” will be removed. Saved queries and history keep their records but
          lose the link to this connection.
        </p>
      </Dialog>

      {/* Schema preview */}
      <Dialog
        open={!!schemaTarget}
        title={`Schema — ${schemaTarget?.name ?? ''}`}
        onClose={() => setSchemaTarget(null)}
        wide
      >
        <SchemaPreview connectionId={schemaTarget?.id ?? null} />
      </Dialog>
    </div>
  );
}

function SchemaPreview({ connectionId }: { connectionId: string | null }) {
  const query = useQuery({
    queryKey: ['schema', connectionId],
    queryFn: () => api<DatabaseSchema>(`/api/connections/${connectionId}/schema?refresh=true`),
    enabled: !!connectionId,
  });

  if (query.isLoading) return <Skeleton className="h-40 w-full" />;
  if (query.isError) return <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />;
  if (!query.data) return null;

  return (
    <div className="max-h-96 space-y-4 overflow-y-auto">
      {query.data.tables.length === 0 && (
        <p className="text-sm text-slate-500">No tables or views found in this database.</p>
      )}
      {query.data.tables.map((t) => (
        <div key={`${t.schema}.${t.name}`} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
          <p className="font-mono text-sm font-semibold">
            {t.schema}.{t.name}{' '}
            <span className="text-xs font-normal text-slate-400">({t.kind})</span>
          </p>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2">
            {t.columns.map((c) => (
              <li key={c.name} className="flex items-center gap-2 font-mono text-xs text-slate-600 dark:text-slate-400">
                {c.name}
                <span className="text-brand-600 dark:text-brand-400">{c.type}</span>
                {c.pk && <Badge tone="brand">PK</Badge>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {query.data.relationships.length > 0 && (
        <div>
          <p className="mb-2 text-sm font-semibold">Relationships</p>
          <ul className="space-y-1 text-xs text-slate-600 dark:text-slate-400">
            {query.data.relationships.map((r, i) => (
              <li key={i} className="font-mono">
                {r.schema}.{r.table}.{r.column} → {r.ref_schema}.{r.ref_table}.{r.ref_column}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
