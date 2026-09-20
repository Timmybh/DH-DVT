import { MutableRefObject, useMemo, useState } from "react";
import { DraftRow, laneId } from "../../lib/draft";
import { num } from "../../lib/format";

export type DragInfo = { kind: "unplanned"; id: number } | { kind: "row"; uid: string } | null;

interface Props {
  rows: DraftRow[];
  factories: string[];
  activeXn: string;
  onXn: (xn: string) => void;
  editable: boolean;
  drag: MutableRefObject<DragInfo>;
  onDropAt: (xn: string, line: string, afterUid: string | null) => void;
  onOpenRow: (row: DraftRow) => void;
  highlightUid: string | null;
  issueMap: Map<string, "ERROR" | "WARNING">;
}

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" }) : "—");
const natural = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });

export default function PlannedBoard({ rows, factories, activeXn, onXn, editable, drag, onDropAt, onOpenRow, highlightUid, issueMap }: Props) {
  const [over, setOver] = useState<string | null>(null);

  const perXn = useMemo(() => {
    const m = new Map<string, number>();
    rows.forEach((r) => m.set(r.factory_code, (m.get(r.factory_code) ?? 0) + 1));
    return m;
  }, [rows]);

  const lanes = useMemo(() => {
    const m = new Map<string, DraftRow[]>();
    rows.filter((r) => r.factory_code === activeXn).forEach((r) => {
      if (!m.has(r.primary_line)) m.set(r.primary_line, []);
      m.get(r.primary_line)!.push(r);
    });
    return [...m.entries()].sort((a, b) => natural(a[0], b[0]));
  }, [rows, activeXn]);

  const dropHandlers = (line: string, afterUid: string | null, key: string) => ({
    onDragOver: (e: React.DragEvent) => {
      if (!editable || !drag.current) return;
      e.preventDefault();
      e.stopPropagation();
      setOver(key);
    },
    onDragLeave: () => setOver((cur) => (cur === key ? null : cur)),
    onDrop: (e: React.DragEvent) => {
      if (!editable || !drag.current) return;
      e.preventDefault();
      e.stopPropagation();
      setOver(null);
      onDropAt(activeXn, line, afterUid);
    },
  });

  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm" data-testid="planned-board">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Kế hoạch vận hành (Planned)</h2>
          <p className="text-[11px] text-slate-500">
            {rows.length.toLocaleString("vi-VN")} dòng · {editable ? "kéo dòng để đổi thứ tự/chuyền, thả PO từ Unplanned vào giữa các dòng" : "View Mode"}
          </p>
        </div>
        <div className="flex rounded-lg bg-slate-100 p-0.5">
          {factories.map((f) => (
            <button key={f} onClick={() => onXn(f)} className={`rounded-md px-3 py-1 text-xs font-semibold ${activeXn === f ? "bg-white text-brand shadow-sm" : "text-slate-500"}`}>
              {f} <span className="font-normal text-slate-400">({perXn.get(f) ?? 0})</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-3 overflow-x-auto p-3">
        {lanes.length === 0 && <p className="w-full py-10 text-center text-sm text-slate-400">Chưa có dòng kế hoạch cho {activeXn}.</p>}
        {lanes.map(([line, laneRows]) => {
          const headKey = `${laneId(activeXn, line)}#head`;
          const totalQty = laneRows.reduce((s, r) => s + r.quantity, 0);
          return (
            <div key={line} className="w-[270px] shrink-0 rounded-xl border border-slate-200 bg-slate-50">
              <div
                {...dropHandlers(line, null, headKey)}
                className={`flex items-center justify-between rounded-t-xl border-b px-3 py-2 text-xs ${over === headKey ? "border-brand bg-indigo-100" : "border-slate-200 bg-slate-100"}`}
              >
                <span className="font-bold text-slate-700">Chuyền {line}</span>
                <span className="text-slate-500">{laneRows.length} dòng · {num(totalQty)}</span>
              </div>
              <div
                {...dropHandlers(line, laneRows[laneRows.length - 1]?.row_uid ?? null, `${laneId(activeXn, line)}#body`)}
                className={`max-h-[420px] space-y-1.5 overflow-y-auto p-2 ${over === `${laneId(activeXn, line)}#body` ? "bg-indigo-50" : ""}`}
              >
                {laneRows.map((r) => {
                  const overrides = Object.keys(r.extra?.overrides ?? {});
                  const issue = issueMap.get(r.row_uid);
                  const key = `${r.row_uid}#row`;
                  return (
                    <div
                      key={r.row_uid}
                      id={`row-${r.row_uid}`}
                      draggable={editable}
                      onDragStart={(e) => {
                        e.dataTransfer.setData("text/plain", r.row_uid);
                        e.dataTransfer.effectAllowed = "move";
                        drag.current = { kind: "row", uid: r.row_uid };
                      }}
                      onDragEnd={() => {
                        drag.current = null;
                        setOver(null);
                      }}
                      onClick={() => onOpenRow(r)}
                      {...dropHandlers(line, r.row_uid, key)}
                      className={`rounded-lg border bg-white p-2 text-[11px] leading-tight transition ${editable ? "cursor-grab" : "cursor-pointer"} ${
                        highlightUid === r.row_uid ? "animate-blink border-brand ring-2 ring-brand" : over === key ? "border-brand shadow-md" : "border-slate-200 hover:border-slate-300"
                      } ${r._flag === "NEW" ? "border-l-4 border-l-green-500" : r._flag === "MOVED" ? "border-l-4 border-l-sky-500" : r._flag === "EDITED" ? "border-l-4 border-l-amber-400" : ""}`}
                    >
                      <div className="flex items-start justify-between gap-1">
                        <span className="font-bold text-slate-800">{r.po_number || "—"}</span>
                        <span className="font-semibold text-slate-700">{num(r.quantity)}</span>
                      </div>
                      <p className="truncate text-slate-500" title={r.description}>{r.customer} · {r.description}</p>
                      <p className="mt-0.5 text-slate-600">
                        {fmt(r.begin_prod_date)} → {fmt(r.end_prod_date)} <span className="text-slate-400">· CHD {fmt(r.chd)}</span>
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        {r._flag === "NEW" && <span className="rounded bg-green-100 px-1 font-semibold text-green-700">MỚI</span>}
                        {r._flag === "MOVED" && <span className="rounded bg-sky-100 px-1 font-semibold text-sky-700">ĐÃ DỜI</span>}
                        {r.line_assignments.length > 1 && <span className="rounded bg-indigo-100 px-1 font-semibold text-indigo-700" title="Dồn chuyền">{r.line_raw}</span>}
                        {r.transfer && <span className="rounded bg-violet-100 px-1 font-semibold text-violet-700" title="Chuyển chuyền">{r.line_raw}</span>}
                        {overrides.length > 0 && (
                          <span className="rounded border border-orange-400 px-1 font-bold text-orange-600" title={`Ghi đè thủ công: ${overrides.join(", ")}`}>!</span>
                        )}
                        {issue && <span className={`h-2 w-2 rounded-full ${issue === "ERROR" ? "bg-red-500" : "bg-amber-400"}`} title={issue === "ERROR" ? "Có lỗi Recheck" : "Có cảnh báo Recheck"} />}
                      </div>
                    </div>
                  );
                })}
                {editable && <div className="rounded-lg border border-dashed border-slate-300 py-2 text-center text-[11px] text-slate-400">thả vào đây = cuối chuyền</div>}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
