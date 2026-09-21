import { useState } from "react";
import { RevenueOverview, RevenueSummaryRow } from "../api/client";
import { num } from "../lib/format";
import Section from "./Section";

interface Props {
  data: RevenueOverview;
  onDrill: (factoryCode: string) => void;
}

type Period = "month" | "ytd";

const TICKS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100];

/** Một dòng so sánh kiểu 100%: phần đậm = % đạt, phần nhạt = giá trị thực hiện, ô bên phải = kế hoạch. */
function ComparisonRow({ row, unit, period, onDrill }: { row: RevenueSummaryRow; unit: string; period: Period; onDrill: (code: string) => void }) {
  const total = row.kind === "TOTAL";
  const pct = row.pct;
  const fill = Math.max(0, Math.min(100, pct ?? 0));
  const pctText = pct === null ? "—" : `${Math.round(pct)}%`;
  const narrow = fill < 14; // vùng đậm quá hẹp để chứa chữ → hiện % ở phần nhạt
  const label = `${row.label}: ${pctText}, thực hiện ${num(row.actual)} ${unit}`;

  return (
    <div
      className={`flex items-center gap-3 rounded-lg ${total ? "border-t border-slate-200 pt-3" : "cursor-pointer hover:bg-indigo-50/60"}`}
      {...(total
        ? { role: "img" }
        : {
            role: "button",
            tabIndex: 0,
            onClick: () => onDrill(row.code),
            onKeyDown: (e: React.KeyboardEvent) => (e.key === "Enter" || e.key === " ") && onDrill(row.code),
          })}
      aria-label={total ? label : `${label}. Bấm để xem chi tiết ${row.code}`}
      data-testid={`rev-row-${row.code}`}
    >
      <div className={`w-24 shrink-0 text-xs sm:w-28 ${total ? "font-bold text-slate-900" : "font-semibold text-slate-700"}`}>
        {row.code === "TONG" ? "Tổng công ty" : row.code}
        {row.kind === "FACTORY" && <span className="hidden text-xs font-normal text-slate-400 sm:inline"> · {row.label}</span>}
      </div>

      <div className={`relative flex-1 overflow-hidden rounded-lg border-2 border-[#04191c] bg-[#0e6b6b] ${total ? "h-9" : "h-7"}`}>
        {row.declared ? (
          <>
            <div className="absolute inset-y-0 left-0 flex items-center justify-end bg-[#1fd8d8] pr-2 text-xs font-bold text-[#04262a]" style={{ width: `${fill}%` }}>
              {!narrow && pctText}
            </div>
            <div className="absolute inset-y-0 flex items-center pl-3 text-xs font-medium text-white" style={{ left: `${fill}%` }}>
              {narrow && <span className="mr-2 font-bold">{pctText}</span>}
              {num(row.actual)}
            </div>
          </>
        ) : (
          <div className="flex h-full items-center pl-3 text-xs text-amber-700">{period === "ytd" ? "Chưa khai báo doanh thu năm" : "Chưa khai báo doanh thu tháng"}</div>
        )}
      </div>

      <div
        className={`flex shrink-0 items-center justify-center rounded-lg border-2 border-[#04191c] bg-[#0e6b6b] px-2 text-xs font-medium text-white ${total ? "h-9 min-w-[76px]" : "h-7 min-w-[76px]"}`}
        title="Kế hoạch"
      >
        {num(row.plan)}
      </div>
    </div>
  );
}

/** Tóm tắt điều hành: chỉ so sánh nhanh. Biểu đồ/phân tích theo ngày nằm trong drill-down (bấm vào khối này). */
export default function RevenueSection({ data, onDrill }: Props) {
  const [y, m] = data.month.split("-");
  const [period, setPeriod] = useState<Period>("month");
  const rows = period === "ytd" ? data.summary_ytd : data.summary;
  const total = rows.find((r) => r.kind === "TOTAL");
  const missing = total?.missing ?? [];

  return (
    <div>
      <Section
        title="Doanh thu / Thực hiện"
        subtitle={`${period === "ytd" ? `Lũy kế năm ${data.year}` : `Tháng ${m}/${y}`} · % đạt so với kế hoạch ${period === "ytd" ? "năm" : "tháng"} ${period === "ytd" ? "" : `· thời gian đã qua ${data.elapsed_pct.toFixed(0)}% `}· đơn vị ${data.unit}`}
        right={
          <div className="flex items-center gap-2">
            <div className="inline-flex overflow-hidden rounded-lg border border-slate-200 text-xs font-medium" role="group" aria-label="Kỳ xem doanh thu">
              {([["month", "Tháng hiện tại"], ["ytd", "Lũy kế"]] as const).map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  aria-pressed={period === k}
                  onClick={() => setPeriod(k)}
                  className={`px-2.5 py-1 ${period === k ? "bg-indigo-800 text-white" : "bg-white text-slate-600 hover:bg-slate-50"}`}
                >
                  {label}
                </button>
              ))}
            </div>
            <span className="hidden text-xs text-slate-400 sm:inline">Bấm vào từng xí nghiệp để xem chi tiết</span>
          </div>
        }
      >
        <div className="flex items-end gap-3 pb-1">
          <div className="w-24 shrink-0 sm:w-28" />
          <div className="relative h-4 flex-1">
            {TICKS.map((t) => (
              <span key={t} className="absolute top-0 -translate-x-1/2 text-[10px] text-slate-400" style={{ left: `${t}%` }}>
                {t % 20 === 0 ? `${t}%` : ""}
                <span className="mx-auto block h-1.5 w-px bg-slate-300" />
              </span>
            ))}
          </div>
          <div className="min-w-[76px] shrink-0 text-center text-[10px] font-semibold uppercase text-slate-400">Kế hoạch</div>
        </div>

        <div className="space-y-1.5">
          {rows.map((row) => (
            <ComparisonRow key={row.code} row={row} unit={data.unit} period={period} onDrill={onDrill} />
          ))}
        </div>

        {missing.length > 0 && total?.declared && (
          <p className="mt-3 text-[11px] text-amber-600">Tổng công ty chưa gồm {missing.join(", ")} (chưa khai báo doanh thu {period === "ytd" ? "năm" : "tháng"}).</p>
        )}
      </Section>
    </div>
  );
}
