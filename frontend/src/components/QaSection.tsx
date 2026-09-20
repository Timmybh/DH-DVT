import { QaSummary } from "../api/client";
import { num } from "../lib/format";
import Section from "./Section";

const FACTORY_COLOR: Record<string, string> = { XN1: "#6366f1", XN2: "#0ea5e9", XN3: "#f59e0b" };

interface Props {
  data: QaSummary;
  onDrill: (category: string) => void;
}

/** QA: Total Defect Count (số lần xuất hiện lỗi) theo nhóm kiểm tra, so sánh XN1 / XN2 / XN3. */
export default function QaSection({ data, onDrill }: Props) {
  const [y, m] = data.month.split("-");
  const max = Math.max(1, ...data.categories.flatMap((c) => c.by_factory.map((b) => b.count ?? 0)));
  const codes = data.categories[0]?.by_factory.map((b) => b.code) ?? [];
  return (
    <Section
      title="Chất lượng (QA)"
      subtitle={`Tổng số lỗi (Total Defect Count) tháng ${m}/${y}${data.latest_day ? ` · dữ liệu đến ${new Date(data.latest_day).toLocaleDateString("vi-VN")}` : ""}`}
      right={
        <div className="flex gap-3 text-[11px] text-slate-500">
          {codes.map((c) => (
            <span key={c} className={`flex items-center gap-1 ${data.selected === c ? "font-bold text-slate-800" : ""}`}>
              <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: FACTORY_COLOR[c] ?? "#94a3b8" }} /> {c}
            </span>
          ))}
        </div>
      }
    >
      {!data.has_data ? (
        <p className="text-sm text-slate-500">Chưa có dữ liệu QA từ eGMF — bấm "Đồng bộ ngay" ở Quản trị → Sync Log.</p>
      ) : (
        <div className="space-y-2.5">
          {data.categories.map((c) => (
            <button
              key={c.key}
              onClick={() => c.connected && onDrill(c.key)}
              disabled={!c.connected}
              data-testid={`qa-${c.key}`}
              className={`grid w-full grid-cols-[110px_1fr_64px] items-center gap-3 rounded-lg px-1 py-1 text-left ${c.connected ? "hover:bg-slate-500/10" : "cursor-default opacity-60"}`}
              aria-label={c.connected ? `${c.label}: tổng ${c.total} lỗi` : `${c.label}: chưa kết nối`}
            >
              <span className="text-sm font-semibold text-slate-700">{c.label}</span>
              {c.connected ? (
                <span className="space-y-1">
                  {c.by_factory.map((b) => (
                    <span key={b.code} className="flex items-center gap-2">
                      <span className="w-8 text-[10px] text-slate-400">{b.code}</span>
                      <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-slate-500/15">
                        <span
                          className="block h-full rounded-full"
                          style={{ width: `${((b.count ?? 0) / max) * 100}%`, background: FACTORY_COLOR[b.code] ?? "#94a3b8", opacity: data.selected && data.selected !== b.code ? 0.45 : 1 }}
                        />
                      </span>
                      <span className="w-12 text-right text-xs tabular-nums text-slate-600">{num(b.count)}</span>
                    </span>
                  ))}
                </span>
              ) : (
                <span className="text-xs text-slate-400">Chưa kết nối (dữ liệu nằm trên DB hipro)</span>
              )}
              <span className="text-right text-sm font-bold tabular-nums text-slate-800">{c.connected ? num(c.total) : "—"}</span>
            </button>
          ))}
        </div>
      )}
    </Section>
  );
}
