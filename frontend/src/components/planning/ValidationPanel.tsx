import { useEffect, useMemo, useState } from "react";
import { RecheckIssue, RecheckResult } from "../../api/client";
import { QuickIssue } from "../../lib/quickCheck";

interface Props {
  result: RecheckResult | null;
  stale: boolean; // đã sửa sau lần Recheck gần nhất -> Needs Recheck
  overrides: { row_uid: string; po_number: string; fields: string[] }[];
  onFocus: (rowUid: string) => void;
  quick?: QuickIssue[]; // kiểm tra nhẹ các ô ngày/năng suất người dùng tự gõ (khác Recheck All Plan)
}

type Mode = "collapsed" | "floating" | "expanded";
type Filter = "ALL" | "ERROR" | "WARNING" | "OVERRIDE" | "QUICK";

const RULE_LABEL: Record<string, string> = {
  QTY_INVALID: "Số lượng không hợp lệ",
  FACTORY_INVALID: "Xí nghiệp không hợp lệ",
  LINE_MISSING: "Thiếu chuyền",
  DATE_ORDER: "Sai thứ tự ngày",
  SEQ_DUP: "Trùng thứ tự",
  ROW_DUP_UID: "Trùng định danh",
  TRANSFER_OUT_OF_RANGE: "Chuyển chuyền ngoài khoảng",
  TRANSFER_SAME_LINE: "Chuyển chuyền trùng chuyền",
  CAPACITY_MISSING: "Thiếu năng suất",
  BEGIN_ON_OFF_DAY: "Vào chuyền ngày OFF",
  CALC_MISMATCH: "Khác kết quả tự tính",
  LATE_VS_CHD: "Trễ so với CHD",
  LINE_OVERLAP: "Chồng lấn với dòng trước",
  LINE_OVERLAP_NEXT: "Chồng lấn với dòng sau",
  CAPACITY_VS_REFERENCE: "Năng suất lệch bảng năng suất chuyền",
  TRANSFER_DATE_MISSING: "Thiếu ngày chuyển chuyền",
  TRANSFER_DEST_UNAVAILABLE: "Chuyền đích không làm việc",
};

export default function ValidationPanel({ result, stale, overrides, onFocus, quick = [] }: Props) {
  const [mode, setMode] = useState<Mode>("floating");
  const [filter, setFilter] = useState<Filter>("ALL");
  const [visibleCount, setVisibleCount] = useState(80);
  const quickCount = quick.length;
  useEffect(() => { if (quickCount > 0) setFilter("QUICK"); }, [quickCount]); // có cảnh báo nhanh mới -> mở thẳng mục đó

  const issues = useMemo<RecheckIssue[]>(() => {
    if (!result) return [];
    return filter === "ERROR" || filter === "WARNING" ? result.issues.filter((i) => i.severity === filter) : filter === "ALL" ? result.issues : [];
  }, [result, filter]);

  const status = !result ? "NONE" : stale ? "STALE" : result.result;
  const badge =
    status === "PASS" ? "bg-green-100 text-green-700" : status === "WARNING" ? "bg-amber-100 text-amber-700" : status === "ERROR" ? "bg-red-100 text-red-700" : status === "STALE" ? "bg-orange-100 text-orange-700" : "bg-slate-100 text-slate-500";
  const label = status === "NONE" ? "Chưa Recheck" : status === "STALE" ? "Needs Recheck" : status;

  if (mode === "collapsed") {
    return (
      <button onClick={() => setMode("floating")} className={`fixed bottom-4 right-4 z-40 rounded-full px-4 py-2 text-xs font-bold shadow-lg ${badge}`}>
        Validation: {label} {result && !stale ? `(${result.counts.ERROR}E · ${result.counts.WARNING}W)` : ""}
      </button>
    );
  }
  const expanded = mode === "expanded";
  return (
    <aside className={`fixed bottom-4 right-4 z-40 flex flex-col rounded-2xl border border-slate-200 bg-white shadow-2xl ${expanded ? "top-20 w-[520px]" : "max-h-[60vh] w-[380px]"}`}>
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-bold text-slate-800">Validation</h3>
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${badge}`}>{label}</span>
        </div>
        <div className="flex gap-1 text-xs text-slate-500">
          <button onClick={() => setMode(expanded ? "floating" : "expanded")} className="rounded px-2 py-1 hover:bg-slate-100">{expanded ? "Thu nhỏ" : "Mở rộng"}</button>
          <button onClick={() => setMode("collapsed")} className="rounded px-2 py-1 hover:bg-slate-100">Ẩn</button>
        </div>
      </div>

      {result && (
        <p className="px-4 pt-2 text-[11px] text-slate-400">
          Trace {result.trace_id} · {result.counts.rows.toLocaleString("vi-VN")} dòng · {result.duration_ms} ms
          {stale ? " · bản nháp đã thay đổi — cần Recheck lại" : ""}
        </p>
      )}
      <div className="flex gap-1 px-4 py-2 text-xs">
        {(
          [
            ["ALL", `Tất cả ${result?.issues.length ?? 0}`],
            ["ERROR", `Lỗi ${result?.counts.ERROR ?? 0}`],
            ["WARNING", `Cảnh báo ${result?.counts.WARNING ?? 0}`],
            ["QUICK", `Kiểm tra nhanh ${quick.length}`],
            ["OVERRIDE", `Ghi đè ! ${overrides.length}`],
          ] as [Filter, string][]
        ).map(([f, l]) => (
          <button key={f} onClick={() => { setFilter(f); setVisibleCount(80); }} className={`rounded-full px-2.5 py-1 font-medium ${filter === f ? "bg-brand text-white" : "bg-slate-100 text-slate-600"}`}>
            {l}
          </button>
        ))}
      </div>

      <div className="flex-1 space-y-1.5 overflow-y-auto px-3 pb-3">
        {(filter === "QUICK" || (filter === "ALL" && quick.length > 0)) && (
          <>
            <p className="px-1 text-[11px] text-slate-400">Chỉ soát các ô ngày bắt đầu / kết thúc / năng suất bạn vừa gõ, so với dòng trước và dòng sau. Kiểm tra toàn bộ: bấm Recheck All Plan.</p>
            {filter === "QUICK" && quick.length === 0 && <p className="p-3 text-xs text-green-600">Không có lệch nào ở các ô đã sửa.</p>}
            {quick.map((i, idx) => (
              <button key={`${i.row_uid}-${i.code}-${idx}`} onClick={() => onFocus(i.row_uid)} className={`w-full rounded-lg border p-2 text-left text-xs hover:shadow ${i.severity === "ERROR" ? "border-red-200 bg-red-50" : "border-amber-200 bg-amber-50"}`}>
                <p className="font-semibold text-slate-800">{RULE_LABEL[i.code] ?? i.code}</p>
                <p className="text-slate-600">{i.message}</p>
              </button>
            ))}
          </>
        )}
        {!result && filter !== "OVERRIDE" && filter !== "QUICK" && <p className="p-3 text-xs text-slate-400">Bấm "Recheck All Plan" để kiểm tra toàn bộ kế hoạch.</p>}
        {result && filter !== "OVERRIDE" && filter !== "QUICK" && issues.length === 0 && <p className="p-3 text-xs text-green-600">Không có mục nào.</p>}
        {filter !== "OVERRIDE" && filter !== "QUICK" &&
          issues.slice(0, visibleCount).map((i, idx) => (
            <button
              key={`${i.row_uid}-${i.rule_code}-${idx}`}
              onClick={() => onFocus(i.row_uid)}
              className={`w-full rounded-lg border p-2 text-left text-xs hover:shadow ${i.severity === "ERROR" ? "border-red-200 bg-red-50" : "border-amber-200 bg-amber-50"}`}
            >
              <p className="font-semibold text-slate-800">
                {RULE_LABEL[i.rule_code] ?? i.rule_code} <span className="font-normal text-slate-500">· {i.po_number || i.row_uid} · {i.column}</span>
              </p>
              <p className="text-slate-600">{i.message}</p>
            </button>
          ))}
        {filter !== "OVERRIDE" && filter !== "QUICK" && issues.length > visibleCount && (
          <button onClick={() => setVisibleCount((c) => c + 200)} className="w-full rounded-lg bg-slate-100 py-1.5 text-xs text-slate-600">
            Hiện thêm ({issues.length - visibleCount} mục)
          </button>
        )}
        {filter === "OVERRIDE" &&
          overrides.map((o) => (
            <button key={o.row_uid} onClick={() => onFocus(o.row_uid)} className="w-full rounded-lg border border-orange-300 bg-orange-50 p-2 text-left text-xs">
              <span className="mr-1 font-bold text-orange-600">!</span>
              <span className="font-semibold">{o.po_number || o.row_uid}</span> · ghi đè: {o.fields.join(", ")}
            </button>
          ))}
        {filter === "OVERRIDE" && overrides.length === 0 && <p className="p-3 text-xs text-slate-400">Không có ô nào bị ghi đè.</p>}
      </div>
    </aside>
  );
}
