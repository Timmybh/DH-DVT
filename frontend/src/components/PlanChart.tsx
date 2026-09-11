import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { FactoryPlanSeries } from "../api/client";

interface PlanChartProps {
  series: FactoryPlanSeries[];
  onSelectFactory: (factoryCode: string) => void;
}

export default function PlanChart({ series, onSelectFactory }: PlanChartProps) {
  const data = series.map((s) => {
    const lastIdx = s.plan.length - 1;
    return {
      factory_code: s.factory_code,
      name: s.factory_name,
      "Kế hoạch": s.plan[lastIdx] ?? 0,
      "Thực hiện": s.actual[lastIdx] ?? 0,
    };
  });

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-semibold text-slate-700">
        Kế hoạch vs Thực hiện — 3 Xí nghiệp &amp; Tổng công ty (ngày gần nhất)
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart
          data={data}
          onClick={(e) => {
            const code = e?.activePayload?.[0]?.payload?.factory_code;
            if (code) onSelectFactory(code);
          }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="name" tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
          <Legend />
          <Bar dataKey="Kế hoạch" fill="#c7d2fe" radius={[4, 4, 0, 0]} cursor="pointer" />
          <Bar dataKey="Thực hiện" fill="#4f46e5" radius={[4, 4, 0, 0]} cursor="pointer" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
