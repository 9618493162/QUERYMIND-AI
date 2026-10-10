import { useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ChartSpec, ExecuteResponse } from '../../types/api';
import { Badge } from '../ui/primitives';
import { EmptyState } from '../ui/feedback';

const PALETTE = [
  '#365ef5', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#84cc16', '#f97316', '#ec4899', '#64748b',
];

type ChartType = 'bar' | 'line' | 'pie' | 'area';

function toChartRows(result: ExecuteResponse, chart: ChartSpec) {
  const xIdx = result.columns.findIndex((c) => c.name === chart.x);
  const yIdx = result.columns.findIndex((c) => c.name === chart.y);
  return result.rows.map((row, i) => ({
    name: xIdx >= 0 ? String(row[xIdx] ?? 'NULL') : String(i),
    value: yIdx >= 0 && typeof row[yIdx] === 'number' ? (row[yIdx] as number) : Number(row[yIdx] ?? 0),
  }));
}

export default function ChartPanel({
  result,
  chart,
}: {
  result: ExecuteResponse;
  chart: ChartSpec | null;
}) {
  const [type, setType] = useState<ChartType | 'table'>((chart?.type as ChartType) ?? 'bar');

  const data = useMemo(() => {
    if (!chart) return [];
    return toChartRows(result, { ...chart, type: type === 'table' ? 'bar' : type }).slice(0, 200);
  }, [result, chart, type]);

  if (!chart || !chart.available || data.length === 0) {
    return (
      <EmptyState
        title="No chart for this result"
        description={
          chart?.reason ??
          'The result shape does not support a chart — for example, zero rows or no numeric column.'
        }
      />
    );
  }

  const yLabel = chart.y ?? 'value';

  return (
    <div className="flex h-full flex-col p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-500">Chart type:</span>
        {(['bar', 'line', 'area', 'pie'] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setType(t)}
            className={`rounded-full px-3 py-1 text-xs font-medium capitalize ${
              type === t
                ? 'bg-brand-600 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300'
            }`}
          >
            {t}
          </button>
        ))}
        <Badge tone="brand">{chart.reason}</Badge>
      </div>

      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {type === 'line' ? (
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.3} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="value" name={yLabel} stroke="#365ef5" strokeWidth={2} dot={data.length < 40} />
            </LineChart>
          ) : type === 'area' ? (
            <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.3} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Area type="monotone" dataKey="value" name={yLabel} stroke="#365ef5" fill="#365ef5" fillOpacity={0.25} />
            </AreaChart>
          ) : type === 'pie' ? (
            <PieChart>
              <Tooltip />
              <Legend />
              <Pie data={data} dataKey="value" nameKey="name" outerRadius={110} label>
                {data.map((_, i) => (
                  <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                ))}
              </Pie>
            </PieChart>
          ) : (
            <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" strokeOpacity={0.3} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="value" name={yLabel} fill="#365ef5" radius={[4, 4, 0, 0]} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
