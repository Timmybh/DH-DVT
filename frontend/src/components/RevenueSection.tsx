import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { RevenueOverview, Tile } from "../api/client";
import { dateVi, num, pct } from "../lib/format";
import Gauge, { gaugeColor } from "./Gauge";
import Section from "./Section";

interface Props {
  data: RevenueOverview;
  today: string;
  onDrill: () => void;
}

function TileBody({ tile, unit }: { tile: Tile; unit: string }) {
  return (
    <dl className="mt-1 w-full space-y-0.5 text-xs">
      <div className="flex justify-between">
        <dt className="text-slate-500">Thực hiện</dt>
        <dd className="font-semibold text-slate-900">{num(tile.actual)}</dd>
      </div>
      <div className="flex justify-between">
        <dt className="text-slate-500">Kế hoạch</dt>
        <dd className="text-slate-700">{num(tile.plan)}</dd>
      </div>
      <div className="flex justify-between">
        <dt className="text-slate-500">Còn lại</dt>
        <dd className="text-slate-700">{num(tile.remaining)}</dd>
      </div>
      <p className="pt-0.5 text-right text-[10px] text-slate-400">{unit}</p>
    </dl>
  );
}

export default function RevenueSection({ data, today, onDrill }: Props) {
  const [y, m] = data.month.split("-");
  const t = new Date(today);
  const dayOfYear = Math.floor((t.getTime() - new Date(t.getFullYear(), 0, 0).getTime()) / 86400000);
  const yearElapsed = t.getFullYear() === Number(y) ? (dayOfYear / 365) * 100 : 100;
  const empty: Tile = { plan: null, actual: null, remaining: null, pct: null };

  const chart = data.trend.map((p) => ({
    day: Number(p.date.slice(8, 10)),
    date: p.date,
    "Kế hoạch": p.plan,
    "Thực hiện": p.actual,
  }));

  return (
    <Section
      title="Doanh thu / Thực hiện"
      subtitle={`Tháng ${m}/${y} · đơn vị ${data.unit}`}
      right={
        <button onClick={onDrill} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">
          Xem chi tiết theo ngày
        </button>
      }
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Gauge label="Ngày gần nhất" sublabel={data.day ? dateVi(data.day.date) : "Chưa có số liệu"} pct={data.day?.pct ?? null} expected={90} onClick={onDrill}>
          <TileBody tile={data.day ?? empty} unit={data.unit} />
        </Gauge>
        <Gauge label={`Tháng ${m}`} sublabel={`Thời gian đã qua ${data.elapsed_pct.toFixed(0)}%`} pct={data.month_tile.pct} expected={data.elapsed_pct} onClick={onDrill}>
          <TileBody tile={data.month_tile} unit={data.unit} />
        </Gauge>
        <Gauge label={`Năm ${y}`} sublabel={`Thời gian đã qua ${yearElapsed.toFixed(0)}%`} pct={data.year_tile.pct} expected={yearElapsed} onClick={onDrill}>
          <TileBody tile={data.year_tile} unit={data.unit} />
        </Gauge>
      </div>

      <div className="mt-5">
        <p className="mb-2 text-xs font-semibold text-slate-500">Kế hoạch vs Thực hiện theo ngày (bấm cột để xem chi tiết)</p>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={chart} onClick={onDrill} margin={{ left: -10, right: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="day" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)}k` : String(v))} />
            <Tooltip
              formatter={(v) => num(v as number)}
              labelFormatter={(_, p) => (p?.[0]?.payload?.date ? dateVi(p[0].payload.date) : "")}
            />
            <Legend />
            <Bar dataKey="Kế hoạch" fill="#c7d2fe" radius={[3, 3, 0, 0]} cursor="pointer" />
            <Bar dataKey="Thực hiện" fill="#4f46e5" radius={[3, 3, 0, 0]} cursor="pointer" />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
              <th className="py-2">Đơn vị</th>
              <th className="py-2 text-right">Tháng: thực hiện / kế hoạch</th>
              <th className="py-2 pl-4">% tháng</th>
              <th className="py-2 pl-4">% năm</th>
            </tr>
          </thead>
          <tbody>
            {data.by_factory.map((f) => (
              <tr key={f.code} className="border-b border-slate-50">
                <td className="py-2 font-medium text-slate-800">{f.name}</td>
                <td className="py-2 text-right text-slate-700">
                  {f.month_declared ? `${num(f.month_actual)} / ${num(f.month_plan)}` : <span className="text-amber-600">Chưa khai báo</span>}
                </td>
                <td className="py-2 pl-4">
                  <Bar100 value={f.month_pct} expected={data.elapsed_pct} />
                </td>
                <td className="py-2 pl-4">
                  <Bar100 value={f.year_pct} expected={yearElapsed} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function Bar100({ value, expected }: { value: number | null; expected: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, value ?? 0)}%`, backgroundColor: gaugeColor(value, expected) }} />
      </div>
      <span className="w-14 text-xs text-slate-600">{pct(value)}</span>
    </div>
  );
}
