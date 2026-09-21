import { useState } from "react";
import { CALCULATED_FIELDS, DraftRow, Op } from "../../lib/draft";

interface Props {
  row: DraftRow;
  editable: boolean;
  onApply: (ops: Op[]) => void;
  onClose: () => void;
  lineOptions?: string[]; // các chuyền hiện có của xí nghiệp (gợi ý)
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
const splitLines = (s: string): string[] => [...new Set(s.split(/[+,;\s]+/).map((x) => x.trim()).filter(Boolean))];

export default function RowEditorModal({ row, editable, onApply, onClose, lineOptions = [] }: Props) {
  const rec = row as unknown as Record<string, unknown>;
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(FIELDS.map((f) => [f.key, str(rec[f.key])])));
  const [transferDate, setTransferDate] = useState(row.transfer?.effective_date ?? "");
  const overrides = row.extra?.overrides ?? {};
  const [linesText, setLinesText] = useState(row.line_assignments.join(" + "));
  const [toText, setToText] = useState("");
  const [effDate, setEffDate] = useState("");
  const [remaining, setRemaining] = useState("");
  const [offValue, setOffValue] = useState("");
  const [offReason, setOffReason] = useState("");
  const off = row.calc?.off_days_detail;
  const newLines = splitLines(linesText);
  const toLines = splitLines(toText);
  const linesChanged = newLines.length > 0 && newLines.join("|") !== row.line_assignments.join("|");
  const sameAsCurrent = toLines.length > 0 && toLines.slice().sort().join("|") === row.line_assignments.slice().sort().join("|");
  const applyNow = (o: Op[]) => {
    onApply(o);
    onClose();
  };

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

        {editable && (
          <div className="mt-4 space-y-3 rounded-xl border border-slate-200 p-3" data-testid="line-editor">
            <p className="text-xs font-bold uppercase text-slate-400">Chuyền</p>
            <label className="block text-xs font-medium text-slate-500">
              Dồn chuyền — chạy đồng thời trên nhiều chuyền (VD 4 + 5 + 9). Chuyền đầu là chuyền chính.
              <input list="row-lines" value={linesText} onChange={(e) => setLinesText(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" aria-label="Danh sách chuyền" />
            </label>
            <datalist id="row-lines">{lineOptions.map((l) => <option key={l} value={l} />)}</datalist>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {newLines.map((l, i) => <span key={l} className={`rounded-full px-2 py-0.5 font-semibold ${i === 0 ? "bg-indigo-100 text-indigo-800" : "bg-slate-100 text-slate-700"}`}>{l}{i === 0 ? " · chính" : ""}</span>)}
              <span className="flex-1" />
              <button type="button" disabled={!linesChanged} onClick={() => applyNow([{ type: "SET_LINES", rowUid: row.row_uid, lines: newLines }])} className="rounded-full bg-brand px-3 py-1 font-semibold text-white disabled:opacity-40" data-testid="apply-lines">Đặt chuyền</button>
            </div>
            <p className="text-[11px] text-slate-400">Năng suất tổng = tổng năng suất từng chuyền nếu mọi chuyền đều có định nghĩa năng suất; ngày sản xuất được tính lại. Đặt chuyền sẽ gỡ chuyển chuyền hiện có.</p>

            <div className="border-t border-slate-100 pt-3">
              <p className="mb-1 text-xs font-medium text-slate-500">Chuyển chuyền — chuyển phần còn lại sang chuyền khác từ ngày hiệu lực</p>
              <div className="grid grid-cols-3 gap-2">
                <label className="text-[11px] text-slate-500">Chuyền đến<input list="row-lines" value={toText} onChange={(e) => setToText(e.target.value)} placeholder={row.transfer?.to ?? "VD 1"} className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm" aria-label="Chuyền đến" /></label>
                <label className="text-[11px] text-slate-500">Ngày hiệu lực<input type="date" value={effDate} onChange={(e) => setEffDate(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm" aria-label="Ngày hiệu lực" /></label>
                <label className="text-[11px] text-slate-500">SL còn lại chuyển đi<input type="number" min={0} max={row.quantity} value={remaining} onChange={(e) => setRemaining(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm" aria-label="SL còn lại" /></label>
              </div>
              {sameAsCurrent && <p className="mt-1 text-[11px] text-red-600" role="alert">Chuyền đến phải khác chuyền hiện tại ({row.line_assignments.join(" + ")}).</p>}
              <div className="mt-2 flex justify-end gap-2 text-xs">
                {row.transfer && <button type="button" onClick={() => applyNow([{ type: "SET_TRANSFER", rowUid: row.row_uid, clear: true }])} className="rounded-full border border-slate-300 px-3 py-1" data-testid="clear-transfer">Gỡ chuyển chuyền</button>}
                <button type="button" disabled={!toLines.length || sameAsCurrent} onClick={() => applyNow([{ type: "SET_TRANSFER", rowUid: row.row_uid, toLines, effectiveDate: effDate || undefined, plannedRemainingQty: remaining === "" ? null : Number(remaining) }])} className="rounded-full bg-brand px-3 py-1 font-semibold text-white disabled:opacity-40" data-testid="apply-transfer">Đặt chuyển chuyền</button>
              </div>
            </div>
          </div>
        )}

        {editable && (
          <div className="mt-4 space-y-2 rounded-xl border border-slate-200 p-3" data-testid="off-days-editor">
            <p className="text-xs font-bold uppercase text-slate-400">OFF DAYS (số ngày nghỉ trong khoảng may) {off?.overridden && <span className="ml-1 rounded border border-orange-400 px-1 font-bold text-orange-600" title="Đang ghi đè">!</span>}</p>
            <p className="text-xs text-slate-500">
              Tính theo Lịch làm việc: <b>{off?.calculated ?? "—"}</b>
              {off?.overridden ? <> · Ghi đè: <b>{off.override}</b> ({off.source === "EXCEL_IMPORT" ? "lấy từ Excel" : "nhập tay"}) · Áp dụng: <b>{off.effective}</b></> : " · chưa ghi đè"}
              {off?.reason ? <span className="block text-slate-400">Lý do: {off.reason}{off.by ? ` — ${off.by}` : ""}</span> : null}
            </p>
            <div className="flex flex-wrap items-end gap-2">
              <input type="number" min={0} step="any" value={offValue} onChange={(e) => setOffValue(e.target.value)} placeholder="Giá trị ghi đè" className="w-32 rounded-lg border border-slate-200 px-2 py-1.5 text-sm" aria-label="OFF DAYS ghi đè" />
              <input value={offReason} onChange={(e) => setOffReason(e.target.value)} placeholder="Lý do (bắt buộc)" className="min-w-[160px] flex-1 rounded-lg border border-slate-200 px-2 py-1.5 text-sm" aria-label="Lý do ghi đè OFF DAYS" />
              <button type="button" disabled={offValue === "" || offReason.trim().length < 3} onClick={() => applyNow([{ type: "SET_OFF_DAYS", rowUid: row.row_uid, value: Number(offValue), reason: offReason.trim(), at: new Date().toISOString() }])} className="rounded-full bg-brand px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40" data-testid="set-off-days">Ghi đè</button>
              {off?.overridden && <button type="button" onClick={() => applyNow([{ type: "RESET_OFF_DAYS", rowUid: row.row_uid }])} className="rounded-full border border-slate-300 px-3 py-1.5 text-xs" data-testid="reset-off-days">Reset to Calculated</button>}
            </div>
          </div>
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
