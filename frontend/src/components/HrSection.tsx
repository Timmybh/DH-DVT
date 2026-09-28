import { useState } from "react";
import { HrOverview } from "../api/client";
import { num } from "../lib/format";
import Section from "./Section";
import { factoryColor } from "../theme/palette";
import { useTheme } from "../theme/ThemeContext";

interface Props {
  data: HrOverview;
  onDrill: () => void;
}

type Period = "today" | "month" | "ytd";
const PERIOD_LABEL: Record<Period, string> = { today: "Hôm nay", month: "Tháng hiện tại", ytd: "Lũy kế" };

const FACTORY_COLOR = new Proxy({} as Record<string, string>, { get: (_t, code: string) => factoryColor(code) }); // màu theo xí nghiệp từ bảng màu trung tâm

/** Số vắng = biên chế − có mặt (chỉ khi có biên chế), hiển thị đỏ canh phải cạnh số có mặt. */
function Absent({ roster, present }: { roster?: number | null; present: number }) {
  if (!roster) return null;
  const n = Math.max(0, roster - present);
  return <span className="pb-1 text-right text-sm font-bold tabular-nums text-red-500" title="Số vắng = biên chế − có mặt" data-testid="hr-absent">{num(n)}</span>;
}

/** Tình hình nhân sự: mỗi xí nghiệp một card (lao động có mặt, số tổ/chuyền, tỷ trọng trong tổng). */
export default function HrSection({ data, onDrill }: Props) {
  useTheme();
  const [period, setPeriod] = useState<Period>("today");
  if (!data.available) {
    return (
      <Section title="Tình hình nhân sự" subtitle="Chưa có dữ liệu lao động">
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-700">Dữ liệu lấy từ sheet LAO ĐỘNG của file kế hoạch SX.</p>
      </Section>
    );
  }
  const view = period === "today" ? data : period === "month" ? data.month_avg : data.ytd_avg;
  const isAvg = period !== "today";
  const presentLabel = isAvg ? "trung bình có mặt" : "lao động có mặt";
  const periodBtns = (
    <div className="inline-flex overflow-hidden rounded-lg border border-slate-200 text-xs font-medium" role="group" aria-label="Kỳ xem nhân sự">
      {(["today", "month", "ytd"] as Period[]).map((k) => (
        <button key={k} type="button" aria-pressed={period === k} onClick={() => setPeriod(k)} className={`px-2.5 py-1 ${period === k ? "bg-indigo-800 text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`}>
          {PERIOD_LABEL[k]}
        </button>
      ))}
    </div>
  );
  if (!view || !view.available) {
    return (
      <Section title="Tình hình nhân sự" subtitle={`Chưa có ảnh chụp lao động nào trong kỳ "${PERIOD_LABEL[period]}"`} right={periodBtns}>
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-700">Trung bình cần ít nhất 1 ngày có ảnh chụp lao động ERP trong kỳ đang chọn.</p>
      </Section>
    );
  }
  const factories = view.by_factory ?? [];
  const companyTotal = view.company_total ?? view.total ?? 0;
  const total = Math.max(1, companyTotal);
  return (
    <Section
      title="Tình hình nhân sự"
      subtitle={view.as_of_text || presentLabel}
      right={<div className="flex items-center gap-2">{periodBtns}<button onClick={onDrill} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50">Xem theo tổ</button></div>}
    >
      <div className={`grid gap-3 ${factories.length > 1 ? "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4" : "grid-cols-1 sm:grid-cols-2"}`} data-testid="hr-cards">
        {factories.map((f) => (
          <button
            key={f.code}
            onClick={onDrill}
            data-testid={`hr-card-${f.code}`}
            className="rounded-xl border border-slate-200 p-4 text-left hover:shadow-md"
            style={{ borderTop: `4px solid ${FACTORY_COLOR[f.code] ?? "#94a3b8"}` }}
            aria-label={`${f.name}: ${f.total} lao động`}
          >
            <p className="text-xs font-semibold uppercase text-slate-400">{f.name}</p>
            <div className="mt-1 flex items-end justify-between gap-2">
              <p className="text-4xl font-bold tabular-nums text-slate-900">{num(f.total)}</p>
              <Absent roster={f.roster} present={f.total} />
            </div>
            <p className="text-[11px] text-slate-400">{presentLabel}{f.roster ? ` / ${num(f.roster)} biên chế` : ""}{f.attendance_pct != null ? ` · ${f.attendance_pct}%` : ""}{f.delta ? ` · ${f.delta > 0 ? "+" : ""}${f.delta} so với lần trước` : ""}</p>
            <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
              <span>{num(f.teams ?? 0)} tổ/chuyền</span>
              <span>{Math.round((f.total / total) * 100)}% tổng</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-500/20">
              <div className="h-full rounded-full" style={{ width: `${(f.total / total) * 100}%`, background: FACTORY_COLOR[f.code] ?? "#94a3b8" }} />
            </div>
          </button>
        ))}
        <button
          onClick={onDrill}
          data-testid="hr-card-TONG"
          className="rounded-xl border border-slate-200 bg-indigo-500/10 p-4 text-left hover:shadow-md"
          style={{ borderTop: "4px solid #a78bfa" }}
          aria-label={`Tổng công ty: ${companyTotal} lao động`}
        >
          <p className="text-xs font-semibold uppercase text-slate-400">Tổng công ty</p>
          <div className="mt-1 flex items-end justify-between gap-2">
            <p className="text-4xl font-bold tabular-nums text-slate-900">{num(companyTotal)}</p>
            <Absent roster={view.company_roster} present={companyTotal} />
          </div>
          <p className="text-[11px] text-slate-400">{presentLabel}{view.company_roster ? ` / ${num(view.company_roster)} biên chế` : ""}{view.company_attendance_pct != null ? ` · ${view.company_attendance_pct}%` : ""}{view.company_delta ? ` · ${view.company_delta > 0 ? "+" : ""}${view.company_delta} so với lần trước` : ""}</p>
          <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
            <span>{num(view.company_teams ?? view.teams ?? 0)} tổ/chuyền</span>
            <span>100%</span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-500/20"><div className="h-full w-full rounded-full" style={{ background: "#a78bfa" }} /></div>
        </button>
      </div>
    </Section>
  );
}
