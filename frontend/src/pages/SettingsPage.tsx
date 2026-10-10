import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Moon, Save, Sun } from 'lucide-react';
import { api, ApiError } from '../services/api';
import type { UserSettings } from '../types/api';
import { Button, Field } from '../components/ui/primitives';
import { ErrorState, Skeleton } from '../components/ui/feedback';
import { useTheme } from '../contexts/ThemeContext';
import { useToast } from '../contexts/ToastContext';
import { useAuth } from '../contexts/AuthContext';

interface SettingsResponse {
  success: boolean;
  settings: UserSettings;
}

export default function SettingsPage() {
  const { user } = useAuth();
  const { push } = useToast();
  const { theme, setTheme, resolved } = useTheme();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<UserSettings>({
    theme: 'system',
    default_chart_type: 'auto',
    default_row_limit: 500,
  });

  const query = useQuery({
    queryKey: ['settings'],
    queryFn: () => api<SettingsResponse>('/api/settings'),
  });

  useEffect(() => {
    if (query.data) setForm(query.data.settings);
  }, [query.data]);

  const mutation = useMutation({
    mutationFn: (body: UserSettings) =>
      api<SettingsResponse>('/api/settings', { method: 'PATCH', body }),
    onSuccess: (data) => {
      setForm(data.settings);
      queryClient.setQueryData(['settings'], data);
      push('Settings saved.', 'success');
    },
    onError: (err) => push(err instanceof ApiError ? err.message : 'Could not save settings.', 'error'),
  });

  if (query.isLoading) {
    return (
      <div className="mx-auto max-w-2xl space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="mx-auto max-w-2xl">
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-sm text-slate-500">Preferences are stored with your account and synced on sign-in.</p>
      </div>

      <div className="card p-5">
        <h2 className="text-sm font-semibold">Account</h2>
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-slate-500">Name</dt>
            <dd className="font-medium">{user?.name}</dd>
          </div>
          <div>
            <dt className="text-slate-500">Email</dt>
            <dd className="font-medium">{user?.email}</dd>
          </div>
        </dl>
      </div>

      <div className="card p-5">
        <h2 className="text-sm font-semibold">Appearance</h2>
        <div className="mt-3 flex gap-2">
          {(['light', 'dark', 'system'] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => {
                setTheme(t);
                setForm({ ...form, theme: t });
              }}
              className={`btn ${form.theme === t ? 'btn-primary' : 'btn-secondary'} capitalize`}
            >
              {t === 'light' && <Sun className="h-4 w-4" />}
              {t === 'dark' && <Moon className="h-4 w-4" />}
              {t}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          Currently rendering in <span className="font-medium">{resolved}</span> mode.
        </p>
      </div>

      <div className="card p-5">
        <h2 className="text-sm font-semibold">Query defaults</h2>
        <div className="mt-3">
          <Field label="Default chart type">
            <select
              className="input"
              value={form.default_chart_type}
              onChange={(e) => setForm({ ...form, default_chart_type: e.target.value as UserSettings['default_chart_type'] })}
            >
              <option value="auto">Automatic</option>
              <option value="bar">Bar</option>
              <option value="line">Line</option>
              <option value="pie">Pie</option>
              <option value="table">Table</option>
            </select>
          </Field>
          <Field label="Default row limit" hint="10 – 10,000 rows">
            <input
              type="number"
              min={10}
              max={10000}
              className="input"
              value={form.default_row_limit}
              onChange={(e) => setForm({ ...form, default_row_limit: Number(e.target.value) })}
            />
          </Field>
        </div>
        <Button
          loading={mutation.isPending}
          onClick={() => mutation.mutate(form)}
          icon={<Save className="h-4 w-4" />}
        >
          Save settings
        </Button>
      </div>
    </div>
  );
}
