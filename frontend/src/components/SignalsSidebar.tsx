import { useState } from "react";
import { Drill, Signal } from "../api/client";

interface Props {
  good: Signal[];
  warn: Signal[];
  onDrill: (drill: Drill) => void;
}

const COLLAPSED_COUNT = 5;
const EXPANDED_MAX_H = 320; // mở rộng thì cuộn trong khung này thay vì đẩy dài trang

/** Tiêu đề tin: nhãn (Tin nóng, Báo động...) hiển thị thành chip riêng, phần lời ghép đi sau. */
function SignalTitle({ s, hot }: { s: Signal; hot: boolean }) {
  const body = s.tag && s.title.startsWith(`${s.tag}: `) ? s.title.slice(s.tag.length + 2) : s.title;
  return (
    <p className="text-xs font-semibold text-slate-800">
      {s.tag && <span className={`mr-1 rounded px-1 py-0.5 text-[9px] font-bold uppercase ${hot ? "bg-red-500 text-white" : "bg-emerald-500 text-white"}`}>{s.tag}</span>}
      {body}
    </p>
  );
}

interface CardProps {
  items: Signal[];
  onDrill: (drill: Drill) => void;
}

/** Danh sách tin: mặc định chỉ 5 dòng, còn lại thì "... xem thêm N" mở khung cuộn riêng thay vì đẩy dài cả sidebar. */
function useExpandable<T>(items: T[]) {
  const [expanded, setExpanded] = useState(false);
  const hidden = Math.max(0, items.length - COLLAPSED_COUNT);
  const shown = expanded ? items : items.slice(0, COLLAPSED_COUNT);
  return { expanded, setExpanded, hidden, shown };
}

export function GoodNewsCard({ items: good, onDrill }: CardProps) {
  const { expanded, setExpanded, hidden, shown } = useExpandable(good);
  return (
      <div className="rounded-xl border border-green-200 bg-green-50/60 p-2.5">
        <div className="mb-1.5 flex items-center justify-between">
          <h3 className="text-xs font-bold text-green-800">Tin tốt</h3>
          <span className="rounded-full bg-green-100 px-1.5 py-0.5 text-[10px] font-semibold text-green-700">{good.length}</span>
        </div>
        <div className={`space-y-1.5 ${expanded ? "overflow-y-auto pr-0.5" : ""}`} style={expanded ? { maxHeight: EXPANDED_MAX_H } : undefined}>
          {good.length === 0 && <p className="text-[11px] text-slate-500">Chưa có tín hiệu tích cực.</p>}
          {shown.map((s) => (
            <button
              key={s.id}
              onClick={() => s.drill && onDrill(s.drill)}
              className="w-full rounded-lg border border-green-200 bg-white p-2 text-left hover:border-green-400 hover:shadow-sm"
            >
              <SignalTitle s={s} hot={false} />
              {s.detail && <p className="mt-0.5 text-[10px] text-slate-500">{s.detail}</p>}
            </button>
          ))}
        </div>
        {hidden > 0 && (
          <button onClick={() => setExpanded((v) => !v)} className="mt-1.5 w-full text-center text-[10px] font-semibold text-green-700 hover:underline">
            {expanded ? "Thu gọn" : `… xem thêm ${hidden}`}
          </button>
        )}
      </div>
  );
}

export function WarningCard({ items: warn, onDrill }: CardProps) {
  const critical = warn.filter((s) => s.severity === "CRITICAL").length;
  const { expanded, setExpanded, hidden, shown } = useExpandable(warn);
  return (
      <div className="rounded-xl border border-slate-200 bg-white p-2.5">
        <div className="mb-1.5 flex items-center justify-between">
          <h3 className="text-xs font-bold text-slate-800">Cảnh báo / Cần chú ý</h3>
          <span
            className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold ${
              critical ? "bg-red-100 text-red-700" : warn.length ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500"
            }`}
          >
            {warn.length}
          </span>
        </div>
        <div className={`space-y-1.5 ${expanded ? "overflow-y-auto pr-0.5" : ""}`} style={expanded ? { maxHeight: EXPANDED_MAX_H } : undefined}>
          {warn.length === 0 && <p className="text-[11px] text-slate-500">Không có cảnh báo.</p>}
          {shown.map((s) => {
            const crit = s.severity === "CRITICAL";
            return (
              <button
                key={s.id}
                onClick={() => s.drill && onDrill(s.drill)}
                className={`w-full rounded-lg border p-2 text-left hover:shadow-sm ${
                  crit ? "animate-blink border-red-300 bg-red-50" : "border-amber-200 bg-amber-50"
                }`}
              >
                <div className="flex items-start gap-1.5">
                  <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${crit ? "bg-red-500" : "bg-amber-500"}`} />
                  <div className="min-w-0">
                    <SignalTitle s={s} hot />
                    {s.detail && <p className="mt-0.5 break-words text-[10px] text-slate-500">{s.detail}</p>}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
        {hidden > 0 && (
          <button onClick={() => setExpanded((v) => !v)} className="mt-1.5 w-full text-center text-[10px] font-semibold text-slate-600 hover:underline">
            {expanded ? "Thu gọn" : `… xem thêm ${hidden}`}
          </button>
        )}
      </div>
  );
}

export default function SignalsSidebar({ good, warn, onDrill }: Props) {
  return (
    <aside className="w-full shrink-0 space-y-2.5 xl:w-80">
      <GoodNewsCard items={good} onDrill={onDrill} />
      <WarningCard items={warn} onDrill={onDrill} />
    </aside>
  );
}
