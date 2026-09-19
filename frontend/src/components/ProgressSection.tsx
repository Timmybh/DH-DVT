import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ProgressOverview } from "../api/client";
import { dateTimeVi, num, pct } from "../lib/format";
import Section from "./Section";

interface Props {
  data: ProgressOverview;
  onDrill: (risk: string) => void;
}

const RISK_TILES = [
  { key: "OK", label: "Đúng hạn", cls: "border-green-200 bg-green-50 text-green-800" },
  { key: "ADVANCE", label: "Sớm hơn kế hoạch", cls: "border-sky-200 bg-sky-50 text-sky-800" },
  { key: "LATE", label: "Nguy cơ trễ hạn", cls: "border-red-300 bg-red-50 text-red-800" },
  { key: "MATERIAL", label: "Thiếu nguyên phụ liệu", cls: "border-amber-200 bg-amber-50 text-amber-800" },
] as const;

export default function ProgressSection({ data, onDrill }: Props) {
  if (!data.available || !data.pipeline || !data.risks) {
    return (
      <Section title="Tiến độ thực hiện" subtitle="Chưa có dữ liệu kế hoạch sản xuất">
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-700">Chưa nhập file kế hoạch SX. Vào màn hình Sync Log để nhập file Excel.</p>
      </Section>
    );
  }
  const { pipeline, risks, risk_qty } = data;
  const steps = [
    { label: "PO mới (chưa xếp lịch)", value: pipeline.new },
    { label: "Đã xếp kế hoạch", value: pipeline.planned },
    { label: "May xong", value: pipeline.sewn },
    { label: "Đã xuất", value: pipeline.shipped },
  ];
  const chart = (data.by_factory ?? []).map((f) => ({
    name: f.code,
    "Đúng hạn": f.ok,
    "Sớm": f.advance,
    "Trễ": f.late,
    "Thiếu NPL": f.material,
  }));

  return (
    <Section
      title="Tiến độ thực hiện"
      subtitle={`${num(data.total_po)} PO · ${num(data.planned_qty)} sản phẩm đã xếp kế hoạch`}
      right={<button onClick={() => onDrill("ALL")} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">Xem danh sách PO</button>}
    >
      <div className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-4">
        {steps.map((s, i) => (
          <div key={s.label} className="relative rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{s.label}</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">{num(s.value)}</p>
            {i < steps.length - 1 && <span className="absolute -right-2.5 top-1/2 z-10 hidden -translate-y-1/2 text-slate-300 sm:block">›</span>}
          </div>
        ))}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {RISK_TILES.map((t) => {
          const count = risks[t.key];
          const blink = t.key === "LATE" && count > 0;
          return (
            <button
              key={t.key}
              onClick={() => onDrill(t.key)}
              className={`rounded-xl border-2 p-3 text-left transition hover:shadow-md ${t.cls} ${blink ? "animate-blink" : ""}`}
            >
              <p className="text-xs font-semibold">{t.label}</p>
              <p className="mt-1 text-2xl font-bold">{num(count)}</p>
              <p className="text-[11px] opacity-70">
                {num(risk_qty?.[t.key])} sp · {pct(data.pipeline!.planned + data.pipeline!.new ? (count / (data.total_po || 1)) * 100 : null)}
              </p>
            </button>
          );
        })}
      </div>

      {chart.length > 1 && (
        <div className="mt-5">
          <p className="mb-2 text-xs font-semibold text-slate-500">PO đã xếp kế hoạch theo đơn vị</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chart} layout="vertical" margin={{ left: 0, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={44} />
              <Tooltip />
              <Legend />
              <Bar dataKey="Đúng hạn" stackId="a" fill="#22c55e" />
              <Bar dataKey="Sớm" stackId="a" fill="#38bdf8" />
              <Bar dataKey="Thiếu NPL" stackId="a" fill="#f59e0b" />
              <Bar dataKey="Trễ" stackId="a" fill="#ef4444" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-3 text-[11px] text-slate-400">
        Nguồn: {data.batch?.filename} · nhập lúc {dateTimeVi(data.batch?.imported_at)}
      </p>
    </Section>
  );
}
