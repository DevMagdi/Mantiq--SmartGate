import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  LoadingBlock,
  Td,
  Th,
  TableShell,
} from "@/components/ui";
import { useTheme } from "@/hooks/useTheme";
import { fetchDashboard } from "@/services/analytics";
import { mediaUrl } from "@/services/api";
import { DECISION_META } from "@/utils/constants";
import { formatPercent, formatTime } from "@/utils/format";

const DECISION_COLORS = {
  allow: "#10b981",
  deny: "#f43f5e",
  unknown: "#f59e0b",
  review: "#0ea5e9",
};

export function DashboardPage(): JSX.Element {
  const { theme } = useTheme();
  const [days, setDays] = useState(7);
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["dashboard", days],
    queryFn: () => fetchDashboard(days),
    refetchInterval: 30_000,
  });

  const chart = useMemo(
    () => ({
      grid: theme === "dark" ? "#1e293b" : "#e2e8f0",
      text: theme === "dark" ? "#94a3b8" : "#64748b",
      tooltip: {
        backgroundColor: theme === "dark" ? "#0f172a" : "#ffffff",
        border: `1px solid ${theme === "dark" ? "#1e293b" : "#e2e8f0"}`,
        borderRadius: 12,
        fontSize: 12,
        color: theme === "dark" ? "#f1f5f9" : "#0f172a",
        boxShadow: "0 12px 32px -16px rgba(15,23,42,0.35)",
      },
    }),
    [theme],
  );

  const trend = useMemo(
    () =>
      (data?.trend ?? []).map((point) => ({
        ...point,
        label: new Date(point.day).toLocaleDateString(undefined, { weekday: "short" }),
      })),
    [data],
  );

  const peak = useMemo(
    () =>
      (data?.peak_hours ?? []).map((point) => ({
        ...point,
        label: `${String(point.hour).padStart(2, "0")}:00`,
      })),
    [data],
  );

  const pie = useMemo(
    () =>
      (data?.decision_breakdown ?? []).map((item) => ({
        ...item,
        color: DECISION_COLORS[item.decision],
        label: DECISION_META[item.decision]?.label ?? item.decision,
      })),
    [data],
  );

  const overview = data?.overview;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Command centre"
        title="Compound overview"
        subtitle="Live gate health, today's traffic and decision quality across the compound."
        actions={
          <>
            <select
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
              className="focus-ring h-10 rounded-xl border border-ink-200 bg-white px-3 text-xs font-semibold text-ink-600 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-300"
              aria-label="Analytics range"
            >
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
            </select>
            <Button variant="outline" size="md" icon="refresh" onClick={() => void refetch()} loading={isFetching && !isLoading}>
              Refresh
            </Button>
            <Link
              to="/live"
              className="focus-ring inline-flex h-10 items-center gap-2 rounded-xl bg-brand-600 px-4 text-sm font-semibold text-white transition hover:bg-brand-500"
            >
              <Icon name="live" className="h-4 w-4" />
              Live monitor
            </Link>
          </>
        }
      />

      {isError ? (
        <Card className="border-rose-200 dark:border-rose-900/60">
          <EmptyState
            icon="alert"
            title="Could not load analytics"
            description={error instanceof Error ? error.message : "Please retry in a moment."}
            action={<Button onClick={() => void refetch()} icon="refresh">Retry</Button>}
          />
        </Card>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Entries today"
          value={overview?.entries_today ?? "—"}
          icon="car"
          tone="brand"
          hint={`${overview?.unique_vehicles_today ?? 0} unique vehicles`}
          trend={overview?.entries_change_pct ?? null}
          loading={isLoading}
        />
        <StatCard
          label="Denied / blocked"
          value={overview?.denied_today ?? "—"}
          icon="shield"
          tone="danger"
          hint={`${overview?.review_today ?? 0} awaiting manual review`}
          loading={isLoading}
        />
        <StatCard
          label="Vehicles inside"
          value={overview?.vehicles_inside ?? "—"}
          icon="gate"
          tone="info"
          hint={`${overview?.exits_today ?? 0} exits today`}
          loading={isLoading}
        />
        <StatCard
          label="Face match rate"
          value={overview ? formatPercent(overview.face_match_rate) : "—"}
          icon="users"
          tone="success"
          hint={`${overview?.cameras_online ?? 0}/${overview?.cameras_total ?? 0} cameras online`}
          loading={isLoading}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Allowed today"
          value={overview?.allowed_today ?? "—"}
          icon="check"
          tone="success"
          hint="Barrier released"
          loading={isLoading}
        />
        <StatCard
          label="Unknown plates"
          value={overview?.unknown_today ?? "—"}
          icon="alert"
          tone="warning"
          hint={`Plate read rate ${formatPercent(overview?.plate_read_rate ?? 0)}`}
          loading={isLoading}
        />
        <StatCard
          label="Active visitors"
          value={overview?.active_visitors ?? "—"}
          icon="visitors"
          tone="info"
          hint={`${overview?.active_permits ?? 0} active permits`}
          loading={isLoading}
        />
        <StatCard
          label="Residents / vehicles"
          value={overview ? `${overview.residents_total} / ${overview.vehicles_total}` : "—"}
          icon="users"
          tone="neutral"
          hint={`${overview?.blacklist_active ?? 0} blacklist entries`}
          loading={isLoading}
        />
      </div>

      {isLoading ? (
        <Card>
          <LoadingBlock label="Loading analytics…" />
        </Card>
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader
                title="Access decisions over time"
                subtitle={`Daily allowed, denied, unknown and review outcomes · last ${days} days`}
                icon="dashboard"
                actions={
                  <div className="flex items-center gap-3 text-[11px] text-ink-500 dark:text-ink-400">
                    <Legend color="#10b981" label="Allowed" />
                    <Legend color="#f43f5e" label="Denied" />
                    <Legend color="#f59e0b" label="Unknown" />
                  </div>
                }
              />
              <div className="h-[290px] px-2 py-4">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trend} margin={{ top: 8, right: 12, left: -18, bottom: 0 }}>
                    <defs>
                      <linearGradient id="allowed" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
                        <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="denied" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#f43f5e" stopOpacity={0.25} />
                        <stop offset="100%" stopColor="#f43f5e" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="4 4" stroke={chart.grid} vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11, fill: chart.text }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: chart.text }} axisLine={false} tickLine={false} allowDecimals={false} />
                    <Tooltip contentStyle={chart.tooltip} />
                    <Area type="monotone" dataKey="allowed" stroke="#10b981" strokeWidth={2} fill="url(#allowed)" />
                    <Area type="monotone" dataKey="denied" stroke="#f43f5e" strokeWidth={2} fill="url(#denied)" />
                    <Area type="monotone" dataKey="unknown" stroke="#f59e0b" strokeWidth={1.5} fill="transparent" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <Card>
              <CardHeader title="Decision mix" subtitle="Share of outcomes in the range" icon="shield" />
              <div className="h-[220px] px-4 pt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={pie} dataKey="count" nameKey="label" innerRadius={55} outerRadius={82} paddingAngle={3}>
                      {pie.map((item) => (
                        <Cell key={item.decision} fill={item.color} stroke="transparent" />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={chart.tooltip} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="space-y-1.5 px-4 pb-4">
                {pie.length === 0 ? (
                  <p className="text-center text-xs text-ink-400">No decisions recorded yet.</p>
                ) : (
                  pie.map((item) => (
                    <div key={item.decision} className="flex items-center justify-between text-xs">
                      <span className="flex items-center gap-2 text-ink-600 dark:text-ink-300">
                        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
                        {item.label}
                      </span>
                      <span className="font-semibold text-ink-800 dark:text-ink-100">
                        {item.count}
                        <span className="ml-1 text-[10px] font-normal text-ink-400">
                          {item.percentage.toFixed(0)}%
                        </span>
                      </span>
                    </div>
                  ))
                )}
              </div>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Peak hours" subtitle="Entries and exits by hour of day" icon="clock" />
              <div className="h-[240px] px-2 py-4">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={peak} margin={{ top: 8, right: 12, left: -18, bottom: 0 }} barGap={2}>
                    <CartesianGrid strokeDasharray="4 4" stroke={chart.grid} vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 10, fill: chart.text }} axisLine={false} tickLine={false} interval={2} />
                    <YAxis tick={{ fontSize: 11, fill: chart.text }} axisLine={false} tickLine={false} allowDecimals={false} />
                    <Tooltip contentStyle={chart.tooltip} cursor={{ fill: theme === "dark" ? "#1e293b55" : "#f1f5f9" }} />
                    <Bar dataKey="entries" fill="#10b981" radius={[4, 4, 0, 0]} maxBarSize={12} />
                    <Bar dataKey="exits" fill="#0ea5e9" radius={[4, 4, 0, 0]} maxBarSize={12} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <Card>
              <CardHeader
                title="Gate performance"
                subtitle="Decisions by gate in the selected range"
                icon="gate"
                actions={
                  <Link to="/settings" className="text-[11px] font-semibold text-brand-600 hover:underline dark:text-brand-400">
                    Manage
                  </Link>
                }
              />
              <div className="divide-y divide-ink-50 dark:divide-ink-800/60">
                {(data?.gate_performance ?? []).map((gate) => (
                  <div key={gate.gate_id} className="flex items-center gap-3 px-4 py-3">
                    <span className="grid h-8 w-8 place-items-center rounded-lg bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-300">
                      <Icon name="gate" className="h-3.5 w-3.5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-semibold text-ink-800 dark:text-ink-100">
                        {gate.gate_name}
                        <span className="ml-1.5 font-mono text-[10px] font-normal text-ink-400">{gate.gate_code}</span>
                      </p>
                      <p className="text-[10px] text-ink-400">
                        {gate.allowed} allowed · {gate.denied} denied · {gate.unknown} unknown
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-bold">{gate.total}</p>
                      <p className="text-[9px] uppercase tracking-wide text-ink-400">events</p>
                    </div>
                  </div>
                ))}
                {(data?.gate_performance ?? []).length === 0 ? (
                  <p className="px-4 py-6 text-center text-xs text-ink-400">No gate activity yet.</p>
                ) : null}
              </div>
            </Card>
          </div>

          <Card>
            <CardHeader
              title="Recent gate activity"
              subtitle="Latest decisions recorded by the vision pipeline"
              icon="logs"
              actions={
                <Link to="/logs" className="text-[11px] font-semibold text-brand-600 hover:underline dark:text-brand-400">
                  Open access logs →
                </Link>
              }
            />
            {(data?.recent_access ?? []).length === 0 ? (
              <EmptyState icon="logs" title="No access events yet" description="Events appear here as soon as a gate decision is recorded." />
            ) : (
              <TableShell>
                <thead>
                  <tr>
                    <Th>Time</Th>
                    <Th>Plate / person</Th>
                    <Th>Gate</Th>
                    <Th>Decision</Th>
                    <Th>Reason</Th>
                    <Th align="right">Snapshot</Th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.recent_access ?? []).slice(0, 8).map((log) => {
                    const meta = DECISION_META[log.decision];
                    const snapshot = mediaUrl(log.snapshot_url ?? log.face_snapshot_url);
                    return (
                      <tr key={log.id} className="transition hover:bg-ink-50/70 dark:hover:bg-ink-800/30">
                        <Td className="whitespace-nowrap text-xs text-ink-500 dark:text-ink-400">
                          {formatTime(log.occurred_at)}
                          <span className="ml-1 text-[10px] text-ink-300 dark:text-ink-600">{log.direction}</span>
                        </Td>
                        <Td>
                          <p className="font-mono text-xs font-semibold uppercase tracking-wide text-ink-900 dark:text-ink-100">
                            {log.plate_number ?? "Pedestrian"}
                          </p>
                          <p className="text-[10px] text-ink-400">
                            {log.resident?.full_name ?? log.visitor?.full_name ?? "Unrecognised"}
                          </p>
                        </Td>
                        <Td className="text-xs">{log.gate?.name ?? "—"}</Td>
                        <Td>
                          <Badge tone={meta.tone} dot>{meta.label}</Badge>
                        </Td>
                        <Td className="max-w-[260px] truncate text-xs text-ink-500 dark:text-ink-400">{log.reason}</Td>
                        <Td align="right">
                          {snapshot ? (
                            <a href={snapshot} target="_blank" rel="noreferrer" className="inline-block">
                              <img src={snapshot} alt="Gate snapshot" className="h-9 w-14 rounded-md border border-ink-200 object-cover dark:border-ink-700" loading="lazy" />
                            </a>
                          ) : (
                            <span className="text-[10px] text-ink-300">—</span>
                          )}
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </TableShell>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }): JSX.Element {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}
