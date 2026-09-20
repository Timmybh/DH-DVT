import { HrOverview } from "../api/client";
import { num } from "../lib/format";
import Section from "./Section";

interface Props {
  data: HrOverview;
  onDrill: () => void;
}

const FACTORY_COLOR: Record<string, string> = { XN1: "#6366f1", XN2: "#0ea5e9", XN3: "#f59e0b" };

/** Tình hình nhân sự: mỗi xí nghiệp một card (lao động có mặt, số tổ/chuyền, tỷ trọng trong tổng). */
export default function HrSection({ data, onDrill }: Props) {
  if (!data.available) {
    return (
      <Section title="Tình hình nhân sự" subtitle="Chưa có dữ liệu lao động">
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-700">Dữ liệu lấy từ sheet LAO ĐỘNG của file kế hoạch SX.</p>
      </Section>
    );
  }
  const factories = data.by_factory ?? [];
  const total = Math.max(1, data.total ?? 0);
  return (
    <Section
      title="Tình hình nhân sự"
      subtitle={`${data.as_of_text || "Lao động có mặt"} · tổng ${num(data.total)} lao động · ${num(data.teams)} tổ/chuyền`}
      right={<button onClick={onDrill} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">Xem theo tổ</button>}
    >
      <div className={`grid gap-3 ${factories.length > 1 ? "grid-cols-1 sm:grid-cols-3" : "grid-cols-1"}`} data-testid="hr-cards">
        {factories.map((f) => (
          <button
            key={f.code}
            onClick={onDrill}
            data-testid={`hr-card-${f.code}`}
            className="rounded-xl border border-slate-200 p-4 text-left transition hover:shadow-md"
            style={{ borderTop: `4px solid ${FACTORY_COLOR[f.code] ?? "#94a3b8"}` }}
            aria-label={`${f.name}: ${f.total} lao động`}
          >
            <p className="text-xs font-semibold uppercase text-slate-400">{f.name}</p>
            <p className="mt-1 text-4xl font-bold tabular-nums text-slate-900">{num(f.total)}</p>
            <p className="text-[11px] text-slate-400">lao động có mặt</p>
            <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
              <span>{num(f.teams ?? 0)} tổ/chuyền</span>
              <span>{Math.round((f.total / total) * 100)}% tổng</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-500/20">
              <div className="h-full rounded-full" style={{ width: `${(f.total / total) * 100}%`, background: FACTORY_COLOR[f.code] ?? "#94a3b8" }} />
            </div>
          </button>
        ))}
      </div>
    </Section>
  );
}
