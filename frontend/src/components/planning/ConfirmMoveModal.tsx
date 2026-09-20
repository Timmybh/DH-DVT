import { DraftRow } from "../../lib/draft";
import { num } from "../../lib/format";

export type PendingMove =
  | { kind: "move"; row: DraftRow; xn: string; line: string; afterUid: string | null; afterPo: string }
  | { kind: "unplan"; row: DraftRow };

interface Props {
  pending: PendingMove;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Pending Drop cho dòng đã có trong kế hoạch: chỉ đổi thứ tự / trả về Unplanned sau khi bấm Xác nhận. */
export default function ConfirmMoveModal({ pending, onConfirm, onCancel }: Props) {
  const r = pending.row;
  const from = `${r.factory_code} / Chuyền ${r.primary_line} (#${r.sequence})`;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-bold text-slate-900">{pending.kind === "unplan" ? "Xác nhận trả về Chưa lên KH" : "Xác nhận di chuyển dòng"}</h3>
        <div className="mt-3 rounded-xl bg-slate-50 p-3 text-sm">
          <p className="font-semibold text-slate-800">PO {r.po_number} · {r.customer}</p>
          <p className="text-xs text-slate-500">{r.description}</p>
          <p className="mt-1 text-xs text-slate-600">SL {num(r.quantity)}</p>
        </div>
        <dl className="mt-3 space-y-1 text-sm">
          <div className="flex justify-between"><dt className="text-slate-500">Từ</dt><dd className="font-medium text-slate-800">{from}</dd></div>
          <div className="flex justify-between">
            <dt className="text-slate-500">Đến</dt>
            <dd className="font-medium text-slate-800">
              {pending.kind === "unplan" ? "Unplanned / Chưa lên KH" : `${pending.xn} / Chuyền ${pending.line} — ${pending.afterUid ? `sau PO ${pending.afterPo}` : "đầu chuyền"}`}
            </dd>
          </div>
        </dl>
        {pending.kind === "unplan" && <p className="mt-3 text-xs text-amber-600">Dòng sẽ rời khỏi kế hoạch; các dòng sau nó trong chuyền cần được Recheck để tính lại ngày.</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy (giữ nguyên)</button>
          <button onClick={onConfirm} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700">Xác nhận</button>
        </div>
      </div>
    </div>
  );
}
