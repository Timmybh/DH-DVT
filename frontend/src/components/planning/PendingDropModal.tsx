import { useState } from "react";
import { UnplannedDto } from "../../api/client";
import { num } from "../../lib/format";

interface Props {
  source: UnplannedDto;
  factories: string[];
  linesByFactory: Map<string, string[]>;
  initialFactory: string;
  initialLine: string;
  onConfirm: (factory: string, line: string, moved: boolean) => void;
  onCancel: () => void;
}

/** Pending Drop (Correction §5): Confirm / Cancel. PO chưa biết XN bắt buộc chọn XN trước khi Confirm. */
export default function PendingDropModal({ source, factories, linesByFactory, initialFactory, initialLine, onConfirm, onCancel }: Props) {
  const known = source.factory_assignment === "KNOWN";
  const [factory, setFactory] = useState(known ? source.factory_code : "");
  const [line, setLine] = useState(known && factory === initialFactory ? initialLine : "");
  const lines = linesByFactory.get(factory) ?? [];
  const canConfirm = !!factory && !!line.trim();
  const laneMoved = factory !== initialFactory || line !== initialLine;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
        <h3 className="text-lg font-bold text-slate-900">Xác nhận đưa vào kế hoạch</h3>
        <div className="mt-3 rounded-xl bg-slate-50 p-3 text-sm">
          <p className="font-semibold text-slate-800">PO {source.po_number} · {source.customer}</p>
          <p className="text-xs text-slate-500">{source.description}</p>
          <p className="mt-1 text-xs text-slate-600">SL {num(source.quantity)} · {source.season} · {source.sport}</p>
        </div>

        <div className="mt-4 space-y-3">
          <label className="block text-xs font-medium text-slate-500">
            Xí nghiệp {known ? "(đã xác định — giữ nguyên)" : <span className="text-red-500">* bắt buộc chọn</span>}
            <select
              value={factory}
              disabled={known}
              onChange={(e) => { setFactory(e.target.value); setLine(""); }}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-100"
            >
              <option value="">— Chọn Xí nghiệp —</option>
              {factories.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </label>
          <label className="block text-xs font-medium text-slate-500">
            Chuyền đích <span className="text-red-500">*</span>
            <input
              list="pending-lines"
              value={line}
              onChange={(e) => setLine(e.target.value)}
              disabled={!factory}
              placeholder={factory ? "Chọn hoặc nhập mã chuyền" : "Chọn Xí nghiệp trước"}
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-100"
            />
            <datalist id="pending-lines">{lines.map((l) => <option key={l} value={l} />)}</datalist>
          </label>
          {laneMoved && canConfirm && <p className="text-xs text-slate-500">Vị trí: cuối chuyền {factory}/{line}.</p>}
          {!laneMoved && canConfirm && <p className="text-xs text-slate-500">Vị trí: đúng chỗ bạn thả trong chuyền.</p>}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy (trả về Unplanned)</button>
          <button onClick={() => onConfirm(factory, line.trim(), laneMoved)} disabled={!canConfirm} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-40">
            Xác nhận
          </button>
        </div>
      </div>
    </div>
  );
}
