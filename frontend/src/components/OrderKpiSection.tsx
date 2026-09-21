import { OrderKpi } from "../api/client";
import { num } from "../lib/format";
import Section from "./Section";

interface Props {
  data: OrderKpi;
  onDrill: (kind: "SEWING" | "FG", status: "ON_TIME" | "LATE" | "OVERDUE") => void;
}

function Cell({ value, tone, label, onClick }: { value: number; tone: "ok" | "late"; label: string; onClick: () => void }) {
  const cls = tone === "ok" ? "border-emerald-400/50 bg-emerald-500/10 text-emerald-700" : "border-rose-400/50 bg-rose-500/10 text-rose-700";
  return (
    <button onClick={onClick} className={`rounded-lg border px-3 py-1.5 text-left hover:brightness-125 ${cls}`} aria-label={`${label}: ${value} PO`}>
      <p className="text-xl font-bold leading-none tabular-nums">{num(value)}</p>
      <p className="mt-0.5 text-[10px] font-medium opacity-80">PO</p>
    </button>
  );
}

/** Order Progress: PO hoàn thành trong tháng, chia Đúng hạn / Trễ, theo hai mốc (may xong, nhập kho thành phẩm). */
export default function OrderKpiSection({ data, onDrill }: Props) {
  const [y, m] = data.month.split("-");
  const rows = [
    { kind: "SEWING" as const, label: "May xong", sub: "Sewing complete", v: data.sewing },
    { kind: "FG" as const, label: "Nhập kho thành phẩm", sub: "FG receipt complete", v: data.fg },
  ];
  return (
    <Section
      title="Tiến độ đơn hàng"
      subtitle={`PO hoàn thành trong tháng ${m}/${y} · đúng hạn = hoàn thành ≤ ngày xuất hàng trên ERP${data.as_of ? ` · dữ liệu đến ${new Date(data.as_of).toLocaleDateString("vi-VN")}` : ""}`}
    >
      {!data.has_data ? (
        <p className="text-sm text-slate-500">Chưa có dữ liệu tiến độ từ ERP — bấm "Đồng bộ ngay" ở Quản trị → Sync Log.</p>
      ) : (
        <div className="space-y-2">
          <div className="grid grid-cols-[minmax(120px,1.2fr)_1fr_1fr] items-center gap-3 text-[11px] font-semibold uppercase text-slate-400">
            <span />
            <span>Đúng hạn (On time)</span>
            <span>Trễ (Late)</span>
          </div>
          {rows.map((r) => (
            <div key={r.kind} className="grid grid-cols-[minmax(120px,1.2fr)_1fr_1fr] items-center gap-3" data-testid={`order-${r.kind}`}>
              <div>
                <p className="text-xs font-bold text-slate-800">{r.label}</p>
                <p className="text-[10px] text-slate-400">{r.sub}</p>
              </div>
              <Cell value={r.v.on_time} tone="ok" label={`${r.label} đúng hạn`} onClick={() => onDrill(r.kind, "ON_TIME")} />
              <Cell value={r.v.late} tone="late" label={`${r.label} trễ`} onClick={() => onDrill(r.kind, "LATE")} />
            </div>
          ))}
          <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
            <button className="underline-offset-2 hover:underline" onClick={() => onDrill("SEWING", "OVERDUE")}>
              {num(data.sewing.overdue_open)} PO quá hạn giao nhưng chưa may xong
            </button>
            <button className="underline-offset-2 hover:underline" onClick={() => onDrill("FG", "OVERDUE")}>
              {num(data.fg.overdue_open)} PO quá hạn chưa nhập kho TP
            </button>
            <span>
              Chưa có hạn giao: {num(data.sewing.no_due)} (may) · {num(data.fg.no_due)} (nhập kho) — không tính đúng/trễ
            </span>
            {data.fg_excluded_customers.length > 0 && <span>Không tính nhập kho: {data.fg_excluded_customers.join(", ")}</span>}
          </div>
        </div>
      )}
    </Section>
  );
}
