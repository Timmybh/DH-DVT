import { useState } from "react";
import { DraftRow } from "../../lib/draft";
import { num } from "../../lib/format";
import { refLineCapacity, type CapDef } from "../../lib/capacityRef";
import { coversAll, formatLines, MAX_LOOSE_LINES, sortLines } from "../../lib/lines";

/** Menu nhỏ mở khi bấm vào ô Chuyền (Edit Mode): Dồn chuyền (nhiều dòng đã tick) / Thêm chuyền (một dòng). */
export function LineMenu({ row, selected, x, y, onMerge, onAdd, onSplit, onClose }: { row: DraftRow; selected: DraftRow[]; x: number; y: number; onMerge: () => void; onAdd: () => void; onSplit: () => void; onClose: () => void }) {
  const canSplit = !row.transfer; // dòng 1 chuyền vẫn tách được (sang chuyền khác)
  const inSelection = selected.some((r) => r.row_uid === row.row_uid);
  const canMerge = selected.length >= 2 && inSelection;
  const hint = selected.length < 2 ? "Tick ít nhất 2 dòng của CÙNG 1 PO rồi bấm vào ô Chuyền của một dòng đã tick" : !inSelection ? "Bấm vào ô Chuyền của một dòng ĐÃ TICK" : `${selected.length} dòng đã tick sẽ gộp thành 1 dòng`;
  return (
    <>
      <div className="fixed inset-0 z-[70]" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} />
      <div className="fixed z-[71] w-64 rounded-xl border border-slate-200 bg-white p-1.5 text-sm text-slate-900 shadow-xl" style={{ left: Math.min(x, window.innerWidth - 270), top: Math.min(y, window.innerHeight - 150) }} role="menu" data-testid="line-menu">
        <p className="px-2 py-1 text-[11px] font-semibold uppercase text-slate-400">Chuyền {row.line_raw || row.primary_line} · PO {row.po_number}</p>
        <button role="menuitem" disabled={!canMerge} onClick={onMerge} className="flex w-full flex-col rounded-lg px-2 py-1.5 text-left hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50" data-testid="menu-merge">
          <span className="font-semibold">Dồn chuyền</span>
          <span className="text-[11px] text-slate-500">{hint}</span>
        </button>
        <button role="menuitem" onClick={onAdd} className="flex w-full flex-col rounded-lg px-2 py-1.5 text-left hover:bg-slate-100" data-testid="menu-add">
          <span className="font-semibold">Thêm chuyền…</span>
          <span className="text-[11px] text-slate-500">Chọn thêm chuyền cho kế hoạch lớn này</span>
        </button>
        <button role="menuitem" disabled={!canSplit} onClick={onSplit} className="flex w-full flex-col rounded-lg px-2 py-1.5 text-left hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50" data-testid="menu-split">
          <span className="font-semibold">Tách chuyền…</span>
          <span className="text-[11px] text-slate-500">{canSplit ? (row.line_assignments.length > 1 ? "Tách chuyền đang dồn, hoặc tách sang chuyền khác" : "Tách một phần sang chuyền khác từ ngày chọn") : "Gỡ chuyển chuyền trước khi tách"}</span>
        </button>
      </div>
    </>
  );
}

/** Trường hợp 2: một kế hoạch lớn cần nhiều chuyền → mở danh sách chuyền để tick → Chấp nhận. */
export function AddLinesModal({ row, options, onAccept, onCancel }: { row: DraftRow; options: string[]; onAccept: (lines: string[], all: boolean) => void; onCancel: () => void }) {
  const current = row.line_assignments;
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [extra, setExtra] = useState("");
  const [all, setAll] = useState(false);
  const list = sortLines([...new Set([...current, ...options])]);
  const toggle = (l: string) => setPicked((cur) => { const n = new Set(cur); n.has(l) ? n.delete(l) : n.add(l); return n; });
  const typed = extra.split(/[+,;\s]+/).map((x) => x.trim()).filter(Boolean);
  const added = all ? list.filter((l) => !current.includes(l)) : [...new Set([...picked, ...typed])].filter((l) => !current.includes(l));
  const result = all ? [current[0], ...list.filter((l) => l !== current[0])] : [...current, ...added];
  const tooMany = !all && result.length > MAX_LOOSE_LINES;
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label="Thêm chuyền">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 text-slate-900 shadow-xl">
        <h3 className="text-lg font-bold">Thêm chuyền — PO {row.po_number}</h3>
        <p className="mt-1 text-xs text-slate-500">{row.factory_code} · SL {num(row.quantity)} · hiện chạy chuyền <b>{current.join(" + ")}</b>. Tick các chuyền cần đưa thêm vào.</p>
        <label className="mt-3 flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold" data-testid="add-lines-all-wrap">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} aria-label="Tất cả chuyền" data-testid="add-lines-all" />
          Tất cả chuyền của {row.factory_code} <span className="font-normal text-slate-500">({list.length} chuyền → hiển thị {formatLines(list)})</span>
        </label>
        <div className={`mt-3 grid max-h-64 grid-cols-4 gap-2 overflow-y-auto ${all ? "opacity-50" : ""}`} data-testid="add-lines-list">
          {list.map((l) => {
            const isCurrent = current.includes(l);
            return (
              <label key={l} className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 text-sm ${isCurrent ? "border-indigo-300 bg-indigo-50 text-indigo-800" : picked.has(l) ? "border-brand bg-indigo-100" : "border-slate-200"}`}>
                <input type="checkbox" checked={all || isCurrent || picked.has(l)} disabled={all || isCurrent} onChange={() => toggle(l)} aria-label={`Chuyền ${l}`} />
                {l}
              </label>
            );
          })}
        </div>
        <label className="mt-3 block text-xs text-slate-500">Chuyền khác (nhập tay, cách nhau bằng dấu phẩy)
          <input value={extra} disabled={all} onChange={(e) => setExtra(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" placeholder="VD 12, 15" />
        </label>
        <p className="mt-3 rounded-lg bg-slate-50 p-2 text-xs text-slate-600">Kết quả: <b data-testid="add-lines-result">{formatLines(result)}</b>{tooMany && <span className="ml-1 text-red-600">— dồn lẻ tối đa {MAX_LOOSE_LINES} chuyền, hoặc chọn Tất cả chuyền</span>}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
          <button onClick={() => onAccept(result, all)} disabled={added.length === 0 || tooMany} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="add-lines-accept">Chấp nhận</button>
        </div>
      </div>
    </div>
  );
}

/** Trường hợp 1: nhiều dòng đã tick → gộp thành 1 dòng (Pending → Confirm/Cancel như các thao tác cấu trúc khác). */
export function MergeLinesModal({ rows, keepUid, allLines, onKeep, onConfirm, onCancel }: { rows: DraftRow[]; keepUid: string; allLines: string[]; onKeep: (uid: string) => void; onConfirm: (all: boolean) => void; onCancel: () => void }) {
  const keep = rows.find((r) => r.row_uid === keepUid) ?? rows[0];
  const ident = (r: DraftRow) => `${r.factory_code}|${r.po_number}`;
  const sameIdentity = rows.every((r) => r.po_number) && new Set(rows.map(ident)).size === 1;
  const hasTransfer = rows.some((r) => r.transfer);
  const lines = [...new Set([keep, ...rows.filter((r) => r !== keep)].flatMap((r) => r.line_assignments))];
  const qty = rows.reduce((s, r) => s + r.quantity, 0);
  const caps = rows.every((r) => r.capacity) ? rows.reduce((s, r) => s + (r.capacity ?? 0), 0) : null;
  const workers = rows.reduce((s, r) => s + (r.ref?.worker ?? 0), 0);
  const covers = coversAll(lines, allLines);
  const problem = !sameIdentity ? "Chỉ dồn được các dòng của cùng 1 PO (cùng xí nghiệp)." : hasTransfer ? "Có dòng đang chuyển chuyền — gỡ chuyển chuyền trước khi dồn." : lines.length > MAX_LOOSE_LINES && !covers ? `Dồn lẻ tối đa ${MAX_LOOSE_LINES} chuyền. Muốn dồn nhiều hơn hãy dồn tất cả chuyền của xí nghiệp (${allLines.length} chuyền).` : "";
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label="Dồn chuyền">
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 text-slate-900 shadow-xl">
        <h3 className="text-lg font-bold">Dồn {rows.length} dòng thành 1 dòng</h3>
        <table className="mt-3 w-full text-left text-xs">
          <thead><tr className="border-b border-slate-100 text-slate-400"><th className="py-1">Giữ</th><th>Chuyền</th><th>PO</th><th className="text-right">SL</th><th className="text-right">Năng suất</th><th className="text-right">Worker</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.row_uid} className="border-b border-slate-50">
                <td className="py-1"><input type="radio" name="keep" checked={r.row_uid === keep.row_uid} onChange={() => onKeep(r.row_uid)} aria-label={`Giữ dòng chuyền ${r.line_raw}`} /></td>
                <td>{r.line_raw || r.primary_line}</td><td>{r.po_number}</td><td className="text-right">{num(r.quantity)}</td><td className="text-right">{r.capacity ? num(r.capacity) : "—"}</td><td className="text-right">{r.ref?.worker ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 rounded-xl bg-indigo-50 p-3 text-sm text-indigo-900" data-testid="merge-result">
          <p className="text-[11px] font-semibold uppercase text-indigo-500">Kết quả — 1 dòng</p>
          <p className="mt-1"><b>Chuyền {formatLines(lines)}</b>{covers ? " — tất cả chuyền" : ""} (chính: {keep.primary_line})</p>
          <p className="text-xs">SL {num(qty)} · năng suất tổng {caps ? num(caps) : "giữ nguyên (thiếu năng suất ở một dòng)"} · worker {workers ? num(workers) : "—"}</p>
        </div>
        <p className="mt-2 text-[11px] text-slate-500">Dòng được giữ lại giữ nguyên thứ tự và định danh; các dòng còn lại được gộp vào (lưu vết trong dòng). Ngày sản xuất được tính lại theo công thức.</p>
        {problem && <p className="mt-2 text-sm text-red-600" role="alert">{problem}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
          <button onClick={() => onConfirm(covers)} disabled={!!problem} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="merge-confirm">Xác nhận dồn</button>
        </div>
      </div>
    </div>
  );
}

/** Chia số lượng cho các chuyền theo năng suất, duyệt từ chuyền có số thứ tự nhỏ nhất xuống; phần dư do làm tròn dồn cho chuyền trên cùng. */
export function allocate(lines: string[], qty: number, capOf: (l: string) => number): { line: string; qty: number }[] {
  const sorted = sortLines(lines);
  const total = sorted.reduce((s, l) => s + capOf(l), 0) || 1;
  const out = sorted.map((l) => ({ line: l, qty: Math.floor((qty * capOf(l)) / total) }));
  out[0].qty += Math.round(qty) - out.reduce((s, a) => s + a.qty, 0);
  return out;
}

/** Tách chuyền: (a) tick chuyền tách khỏi dòng đang dồn, hoặc (b) tách sang chuyền khác (dùng được cả cho dòng chỉ 1 chuyền) → chọn ngày (+ số lượng) → Chấp nhận. */
export function SplitLinesModal({ row, options, capDefs = [], onAccept, onCancel }: { row: DraftRow; options: string[]; capDefs?: CapDef[]; onAccept: (v: { mode: "FROM" | "TO"; lines: string[]; all: boolean; date: string; quantity: number }) => void; onCancel: () => void }) {
  const lines = row.line_assignments;
  const multi = lines.length > 1;
  const [mode, setMode] = useState<"FROM" | "TO">(multi ? "FROM" : "TO");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [all, setAll] = useState(false);
  const [date, setDate] = useState(row.begin_prod_date ?? new Date().toISOString().slice(0, 10));
  const [qtyText, setQtyText] = useState("");
  const targets = sortLines(options.filter((l) => !lines.includes(l)));
  const pool = mode === "FROM" ? lines : targets;
  const chosen = sortLines(mode === "TO" && all ? targets : pool.filter((l) => picked.has(l))); // xếp theo số thứ tự chuyền
  // năng suất từng chuyền: định nghĩa đích danh mã hàng, nếu không có thì bình quân của chuyền; thiếu dữ liệu -> chia đều theo năng suất dòng gốc
  const perLineFallback = (row.capacity ?? 0) / Math.max(1, lines.length) || 1;
  const capOf = (l: string) => refLineCapacity(capDefs, row.factory_code, l, row.style_cc ?? "", row.model_code ?? "")?.value ?? perLineFallback;
  const chosenCap = chosen.reduce((s, l) => s + capOf(l), 0);
  const stayCap = (mode === "FROM" ? lines.filter((l) => !picked.has(l)) : lines).reduce((s, l) => s + capOf(l), 0);
  const share = chosenCap + stayCap > 0 ? chosenCap / (chosenCap + stayCap) : 0;
  const suggested = Math.max(1, Math.round(row.quantity * share));
  const qty = qtyText === "" ? suggested : Number(qtyText);
  const toggle = (l: string) => setPicked((cur) => { const n = new Set(cur); n.has(l) ? n.delete(l) : n.add(l); return n; });
  const stay = mode === "FROM" ? lines.filter((l) => !picked.has(l)) : lines;
  const tooMany = mode === "TO" && !all && chosen.length > MAX_LOOSE_LINES;
  const problem =
    chosen.length === 0 ? (mode === "FROM" ? "Tick ít nhất 1 chuyền để tách." : "Tick chuyền đích cho dòng mới.") :
    mode === "FROM" && stay.length === 0 ? "Phải để lại ít nhất 1 chuyền cho dòng gốc." :
    tooMany ? `Dồn lẻ tối đa ${MAX_LOOSE_LINES} chuyền, hoặc chọn Tất cả chuyền.` :
    !date ? "Chọn ngày tách." :
    !(qty > 0 && qty < row.quantity) ? `Số lượng tách phải > 0 và < ${num(row.quantity)}.` : "";
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label="Tách chuyền">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 text-slate-900 shadow-xl">
        <h3 className="text-lg font-bold">Tách chuyền — PO {row.po_number}</h3>
        <p className="mt-1 text-xs text-slate-500">{row.factory_code} · SL {num(row.quantity)} · đang chạy chuyền <b>{formatLines(lines)}</b>.</p>
        {multi && (
          <div className="mt-3 flex gap-1 rounded-lg bg-slate-100 p-0.5 text-xs font-medium" role="tablist">
            {([["FROM", "Tách chuyền đang dồn"], ["TO", "Tách sang chuyền khác"]] as const).map(([m, label]) => (
              <button key={m} role="tab" aria-selected={mode === m} onClick={() => { setMode(m); setPicked(new Set()); setAll(false); setQtyText(""); }} className={`flex-1 rounded-md px-2 py-1 ${mode === m ? "bg-white shadow-sm" : "text-slate-500"}`} data-testid={`split-mode-${m}`}>{label}</button>
            ))}
          </div>
        )}
        <p className="mt-3 text-xs text-slate-500">{mode === "FROM" ? "Tick các chuyền tách ra thành dòng riêng." : "Tick các chuyền sẽ chạy phần tách ra (dòng mới); dòng gốc giữ nguyên chuyền hiện tại."}</p>
        {mode === "TO" && (
          <label className="mt-2 flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-semibold">
            <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} aria-label="Tất cả chuyền còn lại" data-testid="split-all" /> Tất cả chuyền còn lại <span className="font-normal text-slate-500">({targets.length})</span>
          </label>
        )}
        <div className={`mt-2 grid max-h-52 grid-cols-4 gap-2 overflow-y-auto ${all ? "opacity-50" : ""}`} data-testid="split-lines-list">
          {pool.map((l) => (
            <label key={l} className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 text-sm ${all || picked.has(l) ? "border-brand bg-indigo-100" : "border-slate-200"}`}>
              <input type="checkbox" checked={all || picked.has(l)} disabled={all} onChange={() => toggle(l)} aria-label={`${mode === "FROM" ? "Tách chuyền" : "Chuyền đích"} ${l}`} />
              {l}
            </label>
          ))}
          {pool.length === 0 && <p className="col-span-4 text-xs text-slate-400">Không có chuyền nào khác của {row.factory_code}.</p>}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <label className="block text-xs text-slate-500">Ngày tách (dòng mới bắt đầu từ ngày này)
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" aria-label="Ngày tách" />
          </label>
          <label className="block text-xs text-slate-500">Số lượng tách sang dòng mới
            <input type="number" value={qtyText === "" ? suggested : qtyText} onChange={(e) => setQtyText(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" aria-label="Số lượng tách" />
          </label>
        </div>
        <div className="mt-3 rounded-lg bg-slate-50 p-2 text-xs text-slate-700" data-testid="split-preview">
          <p>Dòng gốc: <b>{formatLines(stay) || "—"}</b> · SL {num(row.quantity - (Number.isFinite(qty) ? qty : 0))}</p>
          <p>Dòng mới: <b>{formatLines(chosen) || "—"}</b> · SL {num(Number.isFinite(qty) ? qty : 0)} · từ {date ? new Date(date + "T00:00:00").toLocaleDateString("vi-VN") : "—"}</p>
          {chosen.length > 1 && Number.isFinite(qty) && qty > 0 && (
            <p className="mt-1" data-testid="split-alloc">Phân bổ từ trên xuống: {allocate(chosen, qty, capOf).map((a) => `chuyền ${a.line}: ${num(a.qty)}`).join(" · ")}</p>
          )}
          <p className="mt-1 text-[11px] text-slate-400">Số lượng gợi ý chia theo năng suất từng chuyền (đích danh mã hàng, hoặc bình quân của chuyền); năng suất và nhân công chia theo định nghĩa từng chuyền (nếu đủ) hoặc chia đều. Có thể sửa số lượng.</p>
        </div>
        {problem && <p className="mt-2 text-sm text-red-600" role="alert">{problem}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
          <button onClick={() => onAccept({ mode, lines: chosen, all: mode === "TO" && all, date, quantity: qty })} disabled={!!problem} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="split-accept">Chấp nhận</button>
        </div>
      </div>
    </div>
  );
}
