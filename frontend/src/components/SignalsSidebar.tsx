import { Drill, Signal } from "../api/client";

interface Props {
  good: Signal[];
  warn: Signal[];
  onDrill: (drill: Drill) => void;
}

interface CardProps {
  items: Signal[];
  onDrill: (drill: Drill) => void;
}

export function GoodNewsCard({ items: good, onDrill }: CardProps) {
  return (
      <div className="rounded-2xl border border-green-200 bg-green-50/60 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-bold text-green-800">Tin tốt</h3>
          <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">{good.length}</span>
        </div>
        <div className="space-y-2">
          {good.length === 0 && <p className="text-xs text-slate-500">Chưa có tín hiệu tích cực.</p>}
          {good.map((s) => (
            <button
              key={s.id}
              onClick={() => s.drill && onDrill(s.drill)}
              className="w-full rounded-lg border border-green-200 bg-white p-3 text-left transition hover:border-green-400 hover:shadow-sm"
            >
              <p className="text-sm font-semibold text-slate-800">{s.title}</p>
              {s.detail && <p className="mt-0.5 text-xs text-slate-500">{s.detail}</p>}
            </button>
          ))}
        </div>
      </div>
  );
}

export function WarningCard({ items: warn, onDrill }: CardProps) {
  const critical = warn.filter((s) => s.severity === "CRITICAL").length;
  return (
      <div className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-800">Cảnh báo / Cần chú ý</h3>
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
              critical ? "bg-red-100 text-red-700" : warn.length ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-500"
            }`}
          >
            {warn.length}
          </span>
        </div>
        <div className="space-y-2">
          {warn.length === 0 && <p className="text-xs text-slate-500">Không có cảnh báo.</p>}
          {warn.map((s) => {
            const crit = s.severity === "CRITICAL";
            return (
              <button
                key={s.id}
                onClick={() => s.drill && onDrill(s.drill)}
                className={`w-full rounded-lg border-2 p-3 text-left transition hover:shadow-sm ${
                  crit ? "animate-blink border-red-300 bg-red-50" : "border-amber-200 bg-amber-50"
                }`}
              >
                <div className="flex items-start gap-2">
                  <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${crit ? "bg-red-500" : "bg-amber-500"}`} />
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-800">{s.title}</p>
                    {s.detail && <p className="mt-0.5 break-words text-xs text-slate-500">{s.detail}</p>}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
  );
}

export default function SignalsSidebar({ good, warn, onDrill }: Props) {
  return (
    <aside className="w-full shrink-0 space-y-4 xl:w-80">
      <GoodNewsCard items={good} onDrill={onDrill} />
      <WarningCard items={warn} onDrill={onDrill} />
    </aside>
  );
}
