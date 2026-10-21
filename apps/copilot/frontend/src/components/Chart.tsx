import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { ChartSpec } from "./GenieResult";

// Loaded on demand (GenieResult lazy-imports it), so the charting library is not part of the first page load.

const COLORS = ["#FF3621", "#2272B4", "#00A972", "#6B4FBB", "#FFAB00", "#1B3139", "#E5484D", "#5F737B"];

const compact = (v: number) =>
  Math.abs(v) >= 1000 ? v.toLocaleString("en-SG", { notation: "compact", maximumFractionDigits: 1 }) : v.toLocaleString("en-SG", { maximumFractionDigits: 4 });

export default function Chart({ spec }: { spec: ChartSpec }) {
  const Shape = spec.time || spec.data.length > 24 ? LineChart : BarChart;
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <Shape data={spec.data} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#EDE8E1" vertical={false} />
          <XAxis dataKey="x" tick={{ fontSize: 11, fill: "#5F737B" }} tickLine={false} axisLine={{ stroke: "#E7E1D8" }} minTickGap={16} />
          <YAxis yAxisId="left" tick={{ fontSize: 11, fill: "#5F737B" }} tickLine={false} axisLine={false} tickFormatter={compact} width={56} />
          {spec.rightAxis ? <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: "#5F737B" }} tickLine={false} axisLine={false} tickFormatter={compact} width={56} /> : null}
          <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #E7E1D8", fontSize: 12 }} formatter={(v) => compact(Number(v))} />
          {spec.series.length > 1 ? <Legend wrapperStyle={{ fontSize: 12 }} iconType="circle" /> : null}
          {spec.series.map((s, i) =>
            Shape === LineChart ? (
              <Line key={s} yAxisId={s === spec.rightAxis ? "right" : "left"} type="monotone" dataKey={s} stroke={COLORS[i % COLORS.length]} strokeWidth={2.2} dot={spec.data.length <= 30} />
            ) : (
              <Bar key={s} yAxisId={s === spec.rightAxis ? "right" : "left"} dataKey={s} fill={COLORS[i % COLORS.length]} radius={[6, 6, 0, 0]} maxBarSize={48} />
            ),
          )}
        </Shape>
      </ResponsiveContainer>
    </div>
  );
}
