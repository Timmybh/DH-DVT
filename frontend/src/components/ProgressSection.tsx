import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ProgressOverview } from "../api/client";
import { dateTimeVi, num, pct } from "../lib/format";
import Section from "./Section";
import { palette } from "../theme/palette";
import { useTheme } from "../theme/ThemeContext";

interface Props {
  data: ProgressOverview;
  onDrill: (risk: string) => void;
  headerColor?: string;
}

type Period = "today" | "month" | "ytd";
const PERIOD_LABEL: Record<Period, string> = { today: "Hôm nay", month: "Tháng hiện tại", ytd: "Lũy kế" };

const RISK_TILES = [
  { key: "OK", label: "Đúng hạn", cls: "border-green-200 bg-green-50 text-green-800" },
  { key: "ADVANCE", label: "Sớm hơn kế hoạch", cls: "border-sky-200 bg-sky-50 text-sky-800" },
  { key: "LATE", label: "Nguy cơ trễ hạn", cls: "border-red-300 bg-red-50 text-red-800" },
  { key: "MATERIAL", label: "Thiếu nguyên phụ liệu", cls: "border-amber-200 bg-amber-50 text-amber-800" },
] as const;

// Tạm ẩn biểu đồ 'PO đã xếp kế hoạch theo đơn vị' (đặt true để hiện lại)
const SHOW_UNIT_CHART = false;

export default function ProgressSection({ data, onDrill, headerColor }: Props) {
  useTheme();
  const [period, setPeriod] = useState<Period>("ytd");
  if (!data.available || !data.pipeline || !data.risks) {
    return (
      <Section title="Tiến độ thực hiện" subtitle="Chưa có dữ liệu kế hoạch sản xuất" headerColor={headerColor}>
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-700">Chưa nhập file kế hoạch SX. Vào màn hình Sync Log để nhập file Excel.</p>
      </Section>
    );
  }
  const { pipeline, risks, risk_qty } = data;
  const sewnShipped =
    period === "today" ? data.pipeline_today : period === "month" ? data.pipeline_month : (data.pipeline_ytd ?? { sewn: pipeline.sewn, shipped: pipeline.shipped });
  const periodBtns = (
    <div className="inline-flex overflow-hidden rounded-lg border border-slate-200 text-xs font-medium" role="group" aria-label="Kỳ xem May xong/Đã xuất">
      {(["today", "month", "ytd"] as Period[]).map((k) => (
        <button key={k} type="button" aria-pressed={period === k} onClick={() => setPeriod(k)} className={`px-2.5 py-1 ${period === k ? "bg-indigo-800 text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`}>
          {PERIOD_LABEL[k]}
        </button>
      ))}
    </div>
  );
  const steps: { label: string; value: number | null; sub?: string; drill?: string }[] = [
    {
      label: "Chưa lên KH (PO mới)",
      value: pipeline.new,
      sub: `${num(pipeline.new_known)} đã biết XN · ${num(pipeline.new_unassigned)} chưa xác định XN`,
      drill: "UNPLANNED",
    },
    { label: "Đã xếp kế hoạch", value: pipeline.planned },
    { label: "May xong", value: sewnShipped?.sewn ?? null },
    { label: "Đã xuất", value: sewnShipped?.shipped ?? null },
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
      headerColor={headerColor}
      subtitle={`${num(data.total_po)} PO · ${num(data.planned_qty)} sản phẩm đã xếp kế hoạch`}
      right={
        <div className="flex items-center gap-2">
          {periodBtns}
          <button onClick={() => onDrill("ALL")} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">Xem danh sách PO</button>
        </div>
      }
    >
      <div className="grid grid-cols-2 items-stretch gap-2 sm:grid-cols-4">
        {steps.map((s, i) => (
          <div
            key={s.label}
            onClick={s.drill ? () => onDrill(s.drill!) : undefined}
            className={`relative rounded-xl border border-slate-200 bg-slate-50 p-3 ${s.drill ? "cursor-pointer hover:border-brand hover:shadow-sm" : ""}`}
          >
            <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{s.label}</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">{num(s.value)}</p>
            {s.sub && <p className="text-[11px] text-slate-500">{s.sub}</p>}
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
              className={`rounded-xl border-2 p-3 text-left hover:shadow-md ${t.cls} ${blink ? "animate-blink" : ""}`}
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

      {SHOW_UNIT_CHART && chart.length > 1 && (
        <div className="mt-5">
          <p className="mb-2 text-xs font-semibold text-slate-500">PO đã xếp kế hoạch theo đơn vị</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chart} layout="vertical" margin={{ left: 0, right: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={44} />
              <Tooltip />
              <Legend />
              <Bar dataKey="Đúng hạn" stackId="a" fill={palette.status.ok} />
              <Bar dataKey="Sớm" stackId="a" fill={palette.status.info} />
              <Bar dataKey="Thiếu NPL" stackId="a" fill={palette.status.warn} />
              <Bar dataKey="Trễ" stackId="a" fill={palette.status.bad} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {!!data.mapping_warnings && (
        <button onClick={() => onDrill("MAPPING")} className="mt-3 rounded-lg bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100">
          {num(data.mapping_warnings)} dòng có cảnh báo mapping XN (dữ liệu nguồn) — xem chi tiết
        </button>
      )}
      <p className="mt-3 text-[11px] text-slate-400">
        Nguồn: {data.batch?.filename} · nhập lúc {dateTimeVi(data.batch?.imported_at)}
      </p>
    </Section>
  );
}
