import { HrOverview } from "../api/client";
import { num } from "../lib/format";
import Section from "./Section";

interface Props {
  data: HrOverview;
  onDrill: () => void;
}

export default function HrSection({ data, onDrill }: Props) {
  if (!data.available) {
    return (
      <Section title="Tình hình nhân sự" subtitle="Chưa có dữ liệu lao động">
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-700">Dữ liệu lấy từ sheet LAO ĐỘNG của file kế hoạch SX.</p>
      </Section>
    );
  }
  const max = Math.max(1, ...(data.by_factory ?? []).map((f) => f.total));
  return (
    <Section
      title="Tình hình nhân sự"
      subtitle={data.as_of_text || "Lao động có mặt"}
      right={<button onClick={onDrill} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">Xem theo tổ</button>}
    >
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <button onClick={onDrill} className="rounded-xl bg-indigo-50 px-6 py-4 text-left transition hover:shadow-md">
          <p className="text-xs font-semibold uppercase text-indigo-500">Lao động có mặt</p>
          <p className="text-4xl font-bold text-indigo-900">{num(data.total)}</p>
          <p className="text-[11px] text-indigo-400">{num(data.teams)} tổ/chuyền</p>
        </button>
        <div className="flex-1 space-y-2">
          {(data.by_factory ?? []).map((f) => (
            <div key={f.code} className="flex items-center gap-3 text-sm">
              <span className="w-24 shrink-0 font-medium text-slate-700">{f.name}</span>
              <div className="h-3 flex-1 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-indigo-500" style={{ width: `${(f.total / max) * 100}%` }} />
              </div>
              <span className="w-12 text-right font-semibold text-slate-800">{num(f.total)}</span>
            </div>
          ))}
        </div>
      </div>
    </Section>
  );
}
