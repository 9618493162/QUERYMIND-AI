import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CheckCircle2,
  Copy,
  Database,
  History as HistoryIcon,
  Loader2,
  MessageSquare,
  Play,
  Save,
  Send,
  Sparkles,
  Table2,
  XCircle,
} from 'lucide-react';
import { api, ApiError } from '../services/api';
import type {
  Conversation,
  ConversationMessage,
  DatabaseConnection,
  ExecuteResponse,
  HistoryItem,
  Paged,
  ValidationReport,
} from '../types/api';
import { Badge, Button, Input } from '../components/ui/primitives';
import { Dialog } from '../components/ui/Dialog';
import { EmptyState, ErrorState, Skeleton } from '../components/ui/feedback';
import SchemaExplorer from '../components/workspace/SchemaExplorer';
import QueryResultsTable from '../components/workspace/QueryResultsTable';
import ChartPanel from '../components/workspace/ChartPanel';
import { useToast } from '../contexts/ToastContext';

const SUGGESTIONS = [
  'Show total sales for each month.',
  'Which products have the highest revenue?',
  'Compare revenue across different regions.',
  'Find the top 10 customers by total spending.',
  'Show customers who have never placed an order.',
  'Find duplicate email addresses.',
  'Count the orders placed this year.',
  'Show the monthly growth rate in sales.',
];

type GenerateResponse = {
  success: boolean;
  sql: string | null;
  explanation: string;
  clarification: string | null;
  validation: ValidationReport | null;
  model: string;
  generation_time_ms: number;
  errors: string[];
};

type PanelTab = 'results' | 'chart' | 'explain';
type SideTab = 'schema' | 'history' | 'conversations';

export default function Workspace() {
  const location = useLocation() as {
    state: {
      question?: string;
      sql?: string;
      connectionId?: string;
      autoExecute?: boolean;
    } | null;
  };
  const { push } = useToast();
  const queryClient = useQueryClient();

  const [connectionId, setConnectionId] = useState<string>(() => localStorage.getItem('querymind.connection') || '');
  const [question, setQuestion] = useState(location.state?.question ?? '');
  const [sql, setSql] = useState(location.state?.sql ?? '');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [validation, setValidation] = useState<ValidationReport | null>(null);
  const [genError, setGenError] = useState<string | null>(null);
  const [clarification, setClarification] = useState<string | null>(null);
  const [explanation, setExplanation] = useState('');
  const [meta, setMeta] = useState<{ model: string; ms: number } | null>(null);
  const [result, setResult] = useState<ExecuteResponse | null>(null);
  const [execError, setExecError] = useState<string | null>(null);
  const [panelTab, setPanelTab] = useState<PanelTab>('results');
  const [sideTab, setSideTab] = useState<SideTab>('schema');
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveForm, setSaveForm] = useState({ title: '', description: '', tags: '' });
  const [pendingConn, setPendingConn] = useState<DatabaseConnection | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);

  const connections = useQuery({
    queryKey: ['connections'],
    queryFn: () => api<{ success: boolean; items: DatabaseConnection[] }>('/api/connections'),
  });

  const historyQuery = useQuery({
    queryKey: ['history'],
    queryFn: () => api<Paged<HistoryItem>>('/api/history?page_size=20'),
    enabled: sideTab === 'history',
  });

  const conversationsQuery = useQuery({
    queryKey: ['conversations'],
    queryFn: () => api<{ success: boolean; items: Conversation[] }>('/api/conversations'),
    enabled: sideTab === 'conversations',
  });

  useEffect(() => {
    if (!connectionId && connections.data?.items.length) {
      const stored = localStorage.getItem('querymind.connection');
      const found = stored ? connections.data.items.find((c) => c.id === stored) : null;
      setConnectionId(found?.id ?? connections.data.items[0].id);
    }
  }, [connections.data, connectionId]);

  useEffect(() => {
    if (connectionId) localStorage.setItem('querymind.connection', connectionId);
  }, [connectionId]);

  // Reopen a query passed in from history/saved pages.
  const reopenRef = useRef<string | null>(null);
  useEffect(() => {
    const st = location.state;
    if (!st) return;
    if (st.connectionId) setConnectionId(st.connectionId);
    if (st.sql) {
      setSql(st.sql);
      setValidation(null);
      setResult(null);
      setGenError(null);
      setClarification(null);
      setExplanation(st.question ? '' : '');
    }
    if (st.question) setQuestion(st.question);
  }, [location.state]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [messages]);

  const connection = useMemo(
    () => connections.data?.items.find((c) => c.id === connectionId) ?? null,
    [connections.data, connectionId],
  );

  const generateMutation = useMutation({
    mutationFn: async (q: string) => {
      let convId = conversationId;
      if (!convId) {
        const created = await api<{ success: boolean; conversation: Conversation }>('/api/conversations', {
          method: 'POST',
          body: { connection_id: connectionId, title: q.slice(0, 80) },
        });
        convId = created.conversation.id;
        setConversationId(convId);
      }
      const data = await api<{
        success: boolean;
        user_message: ConversationMessage;
        assistant_message: ConversationMessage;
        sql: string | null;
        explanation: string;
        clarification: string | null;
        validation: ValidationReport | null;
        model: string;
      }>(`/api/conversations/${convId}/messages`, {
        method: 'POST',
        body: { question: q, connection_id: connectionId },
      });
      return data;
    },
    onSuccess: (data) => {
      setGenError(null);
      setMessages((prev) => [...prev, data.user_message, data.assistant_message]);
      setSql(data.sql ?? '');
      setValidation(data.validation);
      setExplanation(data.explanation);
      setClarification(data.clarification);
      setResult(null);
      setExecError(null);
      setMeta({ model: data.model, ms: 0 });
      if (data.sql && data.validation && !data.validation.valid) {
        setGenError(data.validation.errors.join(' '));
      }
      queryClient.invalidateQueries({ queryKey: ['history'] });
      queryClient.invalidateQueries({ queryKey: ['overview'] });
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
    onError: (err) => {
      setGenError(err instanceof ApiError ? err.message : 'SQL generation failed.');
      setClarification(null);
    },
  });

  const validateMutation = useMutation({
    mutationFn: (value: string) =>
      api<{ success: boolean; validation: ValidationReport }>('/api/query/validate', {
        method: 'POST',
        body: { connection_id: connectionId, sql: value },
      }),
    onSuccess: (data) => {
      setValidation(data.validation);
      if (data.validation.valid) push('SQL passed security validation.', 'success');
      else push('SQL rejected by the security validator.', 'error');
    },
    onError: (err) => push(err instanceof ApiError ? err.message : 'Validation request failed.', 'error'),
  });

  const executeMutation = useMutation({
    mutationFn: (value: string) =>
      api<ExecuteResponse>('/api/query/execute', {
        method: 'POST',
        body: {
          connection_id: connectionId,
          sql: value,
          question: question || '(direct SQL execution)',
          conversation_id: conversationId,
        },
      }),
    onSuccess: (data) => {
      setResult(data);
      setExecError(null);
      setPanelTab('results');
      push(`Query executed — ${data.metadata.returned_rows} rows in ${data.metadata.execution_time_ms} ms.`, 'success');
      queryClient.invalidateQueries({ queryKey: ['history'] });
      queryClient.invalidateQueries({ queryKey: ['overview'] });
    },
    onError: (err) => {
      setResult(null);
      setExecError(err instanceof ApiError ? err.message : 'Query execution failed.');
      queryClient.invalidateQueries({ queryKey: ['history'] });
    },
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      api('/api/saved-queries', {
        method: 'POST',
        body: {
          connection_id: connectionId,
          title: saveForm.title || 'Untitled query',
          description: saveForm.description || null,
          natural_language_question: question,
          sql_query: sql,
          tags: saveForm.tags
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean),
        },
      }),
    onSuccess: () => {
      push('Query saved.', 'success');
      setSaveOpen(false);
      setSaveForm({ title: '', description: '', tags: '' });
      queryClient.invalidateQueries({ queryKey: ['saved'] });
      queryClient.invalidateQueries({ queryKey: ['overview'] });
    },
    onError: (err) => push(err instanceof ApiError ? err.message : 'Could not save the query.', 'error'),
  });

  const ask = (text: string) => {
    const q = text.trim();
    if (!q) return;
    if (!connectionId) {
      push('Select a database connection first.', 'error');
      return;
    }
    setQuestion(q);
    generateMutation.mutate(q);
  };

  const runValidation = () => {
    if (!sql.trim()) return;
    validateMutation.mutate(sql);
  };

  const runExecution = () => {
    if (!sql.trim()) return;
    if (validation && !validation.valid) {
      push('Fix the validation errors before executing.', 'error');
      return;
    }
    executeMutation.mutate(sql);
  };

  const loadConversation = async (id: string) => {
    try {
      const data = await api<{
        success: boolean;
        conversation: Conversation;
        messages: ConversationMessage[];
      }>(`/api/conversations/${id}`);
      setConversationId(id);
      setMessages(data.messages);
      if (data.conversation.connection_id) setConnectionId(data.conversation.connection_id);
      const lastSql = [...data.messages].reverse().find((m) => m.metadata?.sql)?.metadata?.sql;
      if (lastSql) setSql(lastSql);
      push(`Loaded conversation “${data.conversation.title}”.`, 'success');
    } catch (err) {
      push(err instanceof ApiError ? err.message : 'Could not load conversation.', 'error');
    }
  };

  const busy = generateMutation.isPending;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-semibold">AI Query Workspace</h1>
          <p className="text-sm text-slate-500">
            Ask a question, review the SQL, then approve execution.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-slate-400" aria-hidden />
          <select
            className="input w-auto"
            value={connectionId}
            onChange={(e) => {
              setConnectionId(e.target.value);
              setResult(null);
              setValidation(null);
            }}
            aria-label="Database connection"
            disabled={connections.isLoading}
          >
            {connections.isLoading && <option>Loading…</option>}
            {connections.data?.items.length === 0 && <option value="">No connections</option>}
            {connections.data?.items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.database_name})
              </option>
            ))}
          </select>
        </div>
      </div>

      {connections.data && connections.data.items.length === 0 && (
        <EmptyState
          title="No database connections"
          description="Create a connection before generating SQL. The workspace needs a real schema to work with."
          action={
            <Button onClick={() => (window.location.href = '/app/connections')}>Add connection</Button>
          }
        />
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        {/* Main column */}
        <div className="space-y-4">
          {/* Ask */}
          <div className="card p-4">
            <label className="label" htmlFor="question-input">
              Ask your database
            </label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <textarea
                id="question-input"
                className="input min-h-20 flex-1 resize-y font-slate"
                placeholder="e.g. Show the top 10 customers by total spending"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) ask(question);
                }}
              />
              <Button
                onClick={() => ask(question)}
                loading={busy}
                disabled={!question.trim() || !connectionId}
                icon={<Sparkles className="h-4 w-4" />}
                className="sm:self-stretch"
              >
                Generate SQL
              </Button>
            </div>

            <div className="mt-3 flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:border-brand-400 hover:text-brand-600 dark:border-slate-700 dark:text-slate-300"
                  onClick={() => ask(s)}
                  disabled={busy || !connectionId}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Chat thread */}
          {messages.length > 0 && (
            <div className="card max-h-72 overflow-y-auto p-4" ref={threadRef}>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Conversation{conversationId ? '' : ' (new)'}
              </p>
              <div className="space-y-3">
                {messages.map((m) => (
                  <div
                    key={m.id}
                    className={`flex gap-2 ${m.role === 'user' ? 'justify-end' : ''}`}
                  >
                    <div
                      className={`max-w-[85%] rounded-xl px-3 py-2 text-sm ${
                        m.role === 'user'
                          ? 'bg-brand-600 text-white'
                          : 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200'
                      }`}
                    >
                      <p>{m.content}</p>
                      {m.metadata?.sql && (
                        <button
                          type="button"
                          className="mt-1 text-xs underline opacity-90"
                          onClick={() => setSql(m.metadata!.sql!)}
                        >
                          load this SQL
                        </button>
                      )}
                    </div>
                  </div>
                ))}
                {busy && (
                  <div className="flex gap-2 text-sm text-slate-500">
                    <Loader2 className="h-4 w-4 animate-spin" /> Generating with the model…
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Errors / clarification */}
          {genError && (
            <ErrorState
              title="Generation problem"
              message={genError}
              onRetry={() => question && generateMutation.mutate(question)}
            />
          )}
          {clarification && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300">
              <p className="font-semibold">The model needs clarification</p>
              <p className="mt-1">{clarification}</p>
            </div>
          )}

          {/* SQL editor */}
          <div className="card overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-2.5 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold">Generated SQL</h2>
                {validation && (
                  <Badge tone={validation.valid ? 'green' : 'red'}>
                    {validation.valid ? 'validated' : 'rejected'}
                  </Badge>
                )}
                {meta && <Badge>{meta.model}</Badge>}
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Button
                  variant="ghost"
                  onClick={() => {
                    void navigator.clipboard.writeText(sql);
                    push('SQL copied.', 'success');
                  }}
                  disabled={!sql}
                  icon={<Copy className="h-4 w-4" />}
                >
                  Copy
                </Button>
                <Button variant="secondary" onClick={runValidation} loading={validateMutation.isPending} disabled={!sql.trim()}>
                  <CheckCircle2 className="h-4 w-4" /> Validate
                </Button>
                <Button variant="secondary" onClick={() => setSaveOpen(true)} disabled={!sql.trim()} icon={<Save className="h-4 w-4" />}>
                  Save
                </Button>
                <Button
                  onClick={runExecution}
                  loading={executeMutation.isPending}
                  disabled={!sql.trim() || (validation !== null && !validation.valid)}
                  icon={<Play className="h-4 w-4" />}
                >
                  Execute query
                </Button>
              </div>
            </div>

            <textarea
              className="h-44 w-full resize-y bg-slate-950 p-4 font-mono text-xs leading-relaxed text-slate-100 outline-none"
              value={sql}
              onChange={(e) => {
                setSql(e.target.value);
                setValidation(null);
              }}
              placeholder="-- Generated SQL appears here. You can edit it before executing."
              spellCheck={false}
              aria-label="Generated SQL editor"
            />

            {validation && !validation.valid && (
              <div className="border-t border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
                <p className="flex items-center gap-1.5 font-semibold">
                  <XCircle className="h-4 w-4" /> Rejected by security validation
                </p>
                <ul className="mt-1 list-inside list-disc space-y-0.5">
                  {validation.errors.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
            {validation?.valid && (
              <div className="border-t border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
                Read-only statement · tables: {validation.tables.join(', ') || 'none detected'}
              </div>
            )}
          </div>

          {/* Execute error */}
          {execError && <ErrorState title="Execution failed" message={execError} />}

          {/* Results */}
          {result && (
            <div className="card overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-2.5 dark:border-slate-800">
                <div className="flex gap-1">
                  {(
                    [
                      ['results', 'Results', Table2],
                      ['chart', 'Chart', Sparkles],
                      ['explain', 'Explanation', MessageSquare],
                    ] as const
                  ).map(([id, label, Icon]) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setPanelTab(id)}
                      className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium ${
                        panelTab === id
                          ? 'bg-brand-600 text-white'
                          : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                      }`}
                    >
                      <Icon className="h-3.5 w-3.5" /> {label}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-500">
                  <span>{result.metadata.row_count} rows</span>
                  <span>{result.metadata.execution_time_ms} ms</span>
                  {result.metadata.truncated && <Badge tone="amber">truncated</Badge>}
                </div>
              </div>

              <div className="min-h-80">
                {panelTab === 'results' && (
                  <QueryResultsTable
                    result={result}
                    onCopyResults={(text) => {
                      void navigator.clipboard.writeText(text);
                      push('Results copied as TSV.', 'success');
                    }}
                  />
                )}
                {panelTab === 'chart' && <ChartPanel result={result} chart={result.chart} />}
                {panelTab === 'explain' && (
                  <div className="p-4 text-sm leading-relaxed text-slate-700 dark:text-slate-300">
                    <p className="font-semibold">What this query does</p>
                    <p className="mt-2 whitespace-pre-wrap">
                      {explanation || 'No explanation was returned by the model for this query.'}
                    </p>
                    <p className="mt-4 text-xs text-slate-500">
                      Executed in {result.metadata.execution_time_ms} ms ·{' '}
                      {result.metadata.returned_rows} rows returned ·{' '}
                      {(result.metadata.response_bytes / 1024).toFixed(1)} KB payload
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {!result && !execError && (
            <EmptyState
              title="Results will appear here"
              description="Generate SQL from a question, review it, then press “Execute query”. Nothing runs without your approval."
              icon={<Table2 className="h-8 w-8" />}
            />
          )}
        </div>

        {/* Right side panel */}
        <div className="card flex max-h-[80vh] flex-col overflow-hidden lg:sticky lg:top-20">
          <div className="flex border-b border-slate-200 dark:border-slate-800">
            {(
              [
                ['schema', 'Schema', Database],
                ['history', 'History', HistoryIcon],
                ['conversations', 'Chats', MessageSquare],
              ] as const
            ).map(([id, label, Icon]) => (
              <button
                key={id}
                type="button"
                onClick={() => setSideTab(id)}
                className={`flex flex-1 items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium ${
                  sideTab === id
                    ? 'border-b-2 border-brand-600 text-brand-600 dark:text-brand-400'
                    : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                }`}
              >
                <Icon className="h-3.5 w-3.5" /> {label}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-hidden">
            {sideTab === 'schema' && <SchemaExplorer connection={connection} />}
            {sideTab === 'history' && (
              <div className="h-full overflow-y-auto p-3">
                {historyQuery.isLoading ? (
                  <Skeleton className="h-20 w-full" />
                ) : historyQuery.data?.items.length === 0 ? (
                  <p className="text-sm text-slate-500">No history yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {historyQuery.data?.items.map((h) => (
                      <li key={h.id}>
                        <button
                          type="button"
                          className="w-full rounded-lg border border-slate-200 p-2.5 text-left text-xs hover:border-brand-400 dark:border-slate-800"
                          onClick={() => {
                            if (h.generated_sql) {
                              setSql(h.generated_sql);
                              setQuestion(h.question);
                              setValidation(null);
                              setResult(null);
                            }
                          }}
                        >
                          <p className="truncate font-medium">{h.question}</p>
                          <p className="mt-1 text-slate-400">
                            {h.execution_status} · {h.row_count ?? '—'} rows
                          </p>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
            {sideTab === 'conversations' && (
              <div className="h-full overflow-y-auto p-3">
                {conversationsQuery.data?.items.length === 0 ? (
                  <p className="text-sm text-slate-500">No conversations yet. Ask a question to start one.</p>
                ) : (
                  <ul className="space-y-1.5">
                    {conversationsQuery.data?.items.map((c) => (
                      <li key={c.id}>
                        <button
                          type="button"
                          className={`w-full rounded-lg px-2.5 py-2 text-left text-xs hover:bg-slate-100 dark:hover:bg-slate-800 ${
                            c.id === conversationId ? 'bg-brand-50 text-brand-700 dark:bg-brand-950' : ''
                          }`}
                          onClick={() => loadConversation(c.id)}
                        >
                          <p className="truncate font-medium">{c.title}</p>
                          <p className="text-slate-400">{new Date(c.updated_at).toLocaleString()}</p>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Save dialog */}
      <Dialog
        open={saveOpen}
        title="Save query"
        onClose={() => setSaveOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setSaveOpen(false)}>
              Cancel
            </Button>
            <Button loading={saveMutation.isPending} onClick={() => saveMutation.mutate()}>
              Save
            </Button>
          </>
        }
      >
        <label className="label">Title</label>
        <Input
          value={saveForm.title}
          onChange={(e) => setSaveForm({ ...saveForm, title: e.target.value })}
          placeholder="Monthly revenue trend"
        />
        <label className="label mt-3">Description</label>
        <Input
          value={saveForm.description}
          onChange={(e) => setSaveForm({ ...saveForm, description: e.target.value })}
          placeholder="Optional context for your team"
        />
        <label className="label mt-3">Tags</label>
        <Input
          value={saveForm.tags}
          onChange={(e) => setSaveForm({ ...saveForm, tags: e.target.value })}
          placeholder="revenue, monthly"
        />
      </Dialog>
    </div>
  );
}
