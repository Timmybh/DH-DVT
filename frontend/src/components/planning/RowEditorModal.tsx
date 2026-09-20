import { useState } from "react";
import { CALCULATED_FIELDS, DraftRow, Op } from "../../lib/draft";

interface Props {
  row: DraftRow;
  editable: boolean;
  onApply: (ops: Op[]) => void;
  onClose: () => void;
}

const FIELDS: { key: string; label: string; type: "number" | "date" | "text" }[] = [
  { key: "quantity", label: "Số lượng", type: "number" },
  { key: "capacity", label: "Năng suất/ngày (CAPACITY)", type: "number" },
  { key: "total_day", label: "TOTAL DAY (= SL / năng suất)", type: "number" },
  { key: "begin_prod_date", label: "Ngày vào chuyền", type: "date" },
  { key: "end_prod_date", label: "Ngày may xong", type: "date" },
  { key: "warehouse_date", label: "Ngày nhập kho TP", type: "date" },
  { key: "chd", label: "CHD (khách yêu cầu)", type: "date" },
  { key: "note", label: "Ghi chú", type: "text" },
];

const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));

/** Sửa ô dữ liệu: ô tính toán bị sửa tay -> OVERRIDE (viền cam, "!"); có "Return to Auto Calculate" (handoff §9). */
export default function RowEditorModal({ row, editable, onApply, onClose }: Props) {
  const rec = row as unknown as Record<string, unknown>;
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(FIELDS.map((f) => [f.key, str(rec[f.key])])));
  const [transferDate, setTransferDate] = useState(row.transfer?.effective_date ?? "");
  const overrides = row.extra?.overrides ?? {};

  function save() {
    const ops: Op[] = [];
    for (const f of FIELDS) {
      const before = str(rec[f.key]);
      if (vals[f.key] !== before) {
        const value = f.type === "number" ? (vals[f.key] === "" ? null : Number(vals[f.key])) : vals[f.key];
        ops.push({ type: "EDIT_FIELD", rowUid: row.row_uid, field: f.key, value });
      }
    }
    if (row.transfer && transferDate !== (row.transfer.effective_date ?? "")) {
      ops.push({ type: "EDIT_FIELD", rowUid: row.row_uid, field: "transfer_effective_date", value: transferDate });
    }
    if (ops.length) onApply(ops);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-slate-900">PO {row.po_number || row.row_uid}</h3>
        <p className="text-xs text-slate-500">
          {row.customer} · {row.description} · {row.factory_code}/{row.line_raw}
        </p>
        {row.transfer && (
          <p className="mt-2 rounded-lg bg-violet-50 p-2 text-xs text-violet-700">
            Chuyển chuyền {row.transfer.from} ==&gt; {row.transfer.to} — {row.transfer.status}
          </p>
        )}

        <div className="mt-4 space-y-3">
          {FIELDS.map((f) => {
            const overridden = f.key in overrides;
            return (
              <label key={f.key} className="block text-xs font-medium text-slate-500">
                <span className="flex items-center justify-between">
                  <span>
                    {f.label} {overridden && <span className="ml-1 rounded border border-orange-400 px-1 font-bold text-orange-600" title="Đang ghi đè thủ công">!</span>}
                  </span>
                  {overridden && editable && CALCULATED_FIELDS.includes(f.key) && (
                    <button
                      type="button"
                      onClick={() => { onApply([{ type: "RETURN_TO_AUTO_CALC", rowUid: row.row_uid, field: f.key }]); onClose(); }}
                      className="text-[11px] font-semibold text-brand hover:underline"
                    >
                      Return to Auto Calculate
                    </button>
                  )}
                </span>
                <input
                  type={f.type === "number" ? "number" : f.type}
                  value={vals[f.key]}
                  disabled={!editable}
                  onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })}
                  className={`mt-1 w-full rounded-lg border px-3 py-2 text-sm disabled:bg-slate-50 ${overridden ? "border-orange-400" : "border-slate-200"}`}
                />
              </label>
            );
          })}
          {row.transfer && (
            <label className="block text-xs font-medium text-slate-500">
              Ngày hiệu lực chuyển chuyền
              <input type="date" value={transferDate} disabled={!editable} onChange={(e) => setTransferDate(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-50" />
            </label>
          )}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Đóng</button>
          {editable && (
            <button onClick={save} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">
              Áp dụng vào bản nháp
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
