import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import {
  Activity,
  ArrowRight,
  Database,
  History as HistoryIcon,
  MessageSquare,
  Sparkles,
} from 'lucide-react';
import { api } from '../services/api';
import type { AiHealth, OverviewResponse } from '../types/api';
import { EmptyState, ErrorState, Skeleton } from '../components/ui/feedback';
import { Badge } from '../components/ui/primitives';
import { useAuth } from '../contexts/AuthContext';
import { useQuery } from '@tanstack/react-query';

function StatsCard({
  label,
  value,
  icon,
  hint,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500 dark:text-slate-400">{label}</p>
        <span className="text-slate-400">{icon}</span>
      </div>
      <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState('');

  const overview = useQuery({
    queryKey: ['overview'],
    queryFn: () => api<OverviewResponse>('/api/analytics/overview'),
  });

  const ai = useQuery({
    queryKey: ['ai-health'],
    queryFn: () => api<AiHealth>('/api/health/ai'),
    retry: false,
  });

  const stats = overview.data?.stats;
  const hasNoData =
    stats && stats.connections === 0 && stats.total_queries === 0;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Welcome back{user ? `, ${user.name.split(' ')[0]}` : ''}</h1>
        <p className="text-sm text-slate-500">Here is the current state of your QueryMind workspace.</p>
      </div>

      {overview.isLoading && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      )}

      {overview.isError && (
        <ErrorState
          message={(overview.error as Error).message}
          onRetry={() => overview.refetch()}
        />
      )}

      {stats && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatsCard label="Database connections" value={stats.connections} icon={<Database className="h-4 w-4" />} />
          <StatsCard label="Executed queries" value={stats.total_queries} icon={<Activity className="h-4 w-4" />} hint={`${stats.successful_queries} succeeded`} />
          <StatsCard label="Saved queries" value={stats.saved_queries} icon={<HistoryIcon className="h-4 w-4" />} hint={`${stats.favorite_queries} favorites`} />
          <StatsCard
            label="Avg. execution time"
            value={stats.avg_execution_time_ms != null ? `${stats.avg_execution_time_ms} ms` : '—'}
            icon={<Sparkles className="h-4 w-4" />}
          />
        </div>
      )}

      {/* AI + DB status */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">AI provider status</h2>
            {ai.data && (
              <Badge tone={ai.data.status === 'ok' ? 'green' : 'red'}>
                {ai.data.status === 'ok' ? 'Available' : 'Unavailable'}
              </Badge>
            )}
          </div>
          {ai.isLoading ? (
            <Skeleton className="mt-3 h-14 w-full" />
          ) : ai.data ? (
            <div className="mt-3 space-y-1 text-sm text-slate-600 dark:text-slate-400">
              <p>
                <span className="font-medium text-slate-800 dark:text-slate-200">Provider:</span>{' '}
                {ai.data.provider} · {ai.data.model}
              </p>
              <p>{ai.data.message}</p>
              {ai.data.models.length > 0 && (
                <p className="text-xs text-slate-400">Installed: {ai.data.models.join(', ')}</p>
              )}
            </div>
          ) : (
            <ErrorState message="Could not fetch AI provider status." onRetry={() => ai.refetch()} />
          )}
        </div>

        <div className="card p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">Database connections</h2>
            {stats && (
              <Badge tone={stats.connections > 0 ? 'green' : 'slate'}>
                {stats.connections > 0 ? 'Configured' : 'None'}
              </Badge>
            )}
          </div>
          <p className="mt-3 text-sm text-slate-600 dark:text-slate-400">
            {stats && stats.connections > 0
              ? `${stats.connections} connection${stats.connections === 1 ? '' : 's'} available for querying.`
              : 'No database connections yet. Add a connection to start querying real data.'}
          </p>
          <button className="btn-secondary mt-3" onClick={() => navigate('/app/connections')}>
            Manage connections <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Quick query */}
      <div className="card p-5">
        <h2 className="text-sm font-semibold">Ask your database</h2>
        <p className="mt-1 text-sm text-slate-500">
          Start a question here — it opens in the query workspace.
        </p>
        <form
          className="mt-3 flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            navigate('/app/workspace', { state: { question } });
          }}
        >
          <input
            className="input flex-1"
            placeholder="e.g. Show total sales for each month"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            aria-label="Natural language question"
          />
          <button type="submit" className="btn-primary" disabled={!question.trim()}>
            <MessageSquare className="h-4 w-4" /> Generate SQL
          </button>
        </form>
      </div>

      {/* Recent activity */}
      <div className="card">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <h2 className="text-sm font-semibold">Recent activity</h2>
          <button className="text-sm text-brand-600 hover:underline" onClick={() => navigate('/app/history')}>
            View all
          </button>
        </div>
        {overview.isLoading ? (
          <TableSkeletonInline />
        ) : overview.data && overview.data.recent_activity.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title={hasNoData ? 'Welcome to QueryMind AI' : 'No activity yet'}
              description={
                hasNoData
                  ? 'Connect a PostgreSQL database, then ask your first question in the query workspace.'
                  : 'Queries you run will appear here with their status and timing.'
              }
              action={
                <button className="btn-primary" onClick={() => navigate('/app/workspace')}>
                  Open query workspace <ArrowRight className="h-4 w-4" />
                </button>
              }
            />
          </div>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {overview.data?.recent_activity.map((a) => (
              <li key={a.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                <span className="truncate">{a.question}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <Badge tone={a.status === 'success' ? 'green' : a.status === 'failed' || a.status === 'rejected' ? 'red' : 'slate'}>
                    {a.status}
                  </Badge>
                  <span className="tabular-nums text-xs text-slate-400">
                    {a.row_count != null ? `${a.row_count} rows` : ''}
                    {a.execution_time_ms != null ? ` · ${a.execution_time_ms} ms` : ''}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function TableSkeletonInline() {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}
