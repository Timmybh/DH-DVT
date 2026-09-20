import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage, PlanVersion } from "../api/client";
import Section from "../components/Section";
import { useAuth } from "../context/AuthContext";
import { dateTimeVi } from "../lib/format";

interface Diff {
  a: PlanVersion;
  b: PlanVersion;
  summary: Record<string, number>;
  total_changes: number;
  changes: { row_uid: string; po_number: string; category: string; field: string; before: unknown; after: unknown }[];
  truncated: boolean;
}

const CATEGORY_LABEL: Record<string, string> = {
  ADDED: "Thêm dòng",
  REMOVED: "Xóa dòng",
  LINE_CHANGE: "Đổi chuyền/XN",
  MULTI_LINE_CHANGE: "Đổi dồn chuyền",
  SEQUENCE_CHANGE: "Đổi thứ tự",
  QUANTITY_CHANGE: "Đổi số lượng",
  CAPACITY_CHANGE: "Đổi năng suất",
  DATE_CHANGE: "Đổi ngày",
  TRANSFER_CHANGE: "Đổi chuyển chuyền",
  OVERRIDE_CHANGE: "Ghi đè thủ công !",
  FORMULA_RESULT_CHANGE: "Kết quả công thức",
};

const STATUS_CLS: Record<string, string> = {
  ISSUED: "bg-green-100 text-green-700",
  COMMITTED: "bg-sky-100 text-sky-700",
  SUPERSEDED: "bg-slate-100 text-slate-500",
};
const RESULT_CLS: Record<string, string> = { PASS: "bg-green-100 text-green-700", WARNING: "bg-amber-100 text-amber-700", ERROR: "bg-red-100 text-red-700" };
const show = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));

export default function Versions() {
  const { can } = useAuth();
  const [versions, setVersions] = useState<PlanVersion[]>([]);
  const [pick, setPick] = useState<number[]>([]);
  const [diff, setDiff] = useState<Diff | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(0);
  const [from, setFrom] = useState("");

  const load = useCallback(async () => setVersions((await api.get<PlanVersion[]>("/planning/versions")).data), []);
  useEffect(() => {
    load().catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
  }, [load]);

  // Cây phiên bản: v rồi các f con của nó
  const ordered = useMemo(() => {
    const roots = versions.filter((v) => v.minor === null);
    return roots.flatMap((r) => [r, ...versions.filter((c) => c.parent_id === r.id)]);
  }, [versions]);

  const act = async (id: number, fn: () => Promise<string>) => {
    setBusy(id);
    try {
      setMsg({ ok: true, text: await fn() });
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy(0);
      load();
    }
  };

  const doRecheck = (v: PlanVersion) =>
    act(v.id, async () => {
      const r = await api.post(`/planning/versions/${v.id}/recheck`);
      return `${v.code}: Recheck ${r.data.result} (${r.data.counts.ERROR} lỗi, ${r.data.counts.WARNING} cảnh báo)`;
    });
  const doIssue = (v: PlanVersion) =>
    window.confirm(`Issue ${v.code}? Phiên bản đang ISSUED (nếu có) sẽ chuyển SUPERSEDED.`) &&
    act(v.id, async () => {
      await api.post(`/planning/versions/${v.id}/issue`);
      return `Đã Issue ${v.code}.`;
    });

  async function compare() {
    if (pick.length !== 2) return;
    try {
      setDiff((await api.get<Diff>("/planning/compare", { params: { a: pick[0], b: pick[1] } })).data);
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  }

  async function baseline() {
    try {
      const r = await api.post("/planning/baseline", { from_date: from || null });
      setMsg({ ok: true, text: `Đã tạo ${r.data.version.code}: ${r.data.rows.toLocaleString("vi-VN")} dòng (Recheck ${r.data.recheck}).` });
      load();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  }

  const toggle = (id: number) => setPick((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id]));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Phiên bản kế hoạch</h1>
          <p className="text-xs text-slate-500">Commit tạo phiên bản bất biến · chỉ Issue được phiên bản có Recheck = PASS · Issue mới làm phiên bản cũ SUPERSEDED.</p>
        </div>
        {can("planning.commit") && (
          <div className="flex items-center gap-2">
            <label className="text-xs text-slate-500">Dòng kết thúc từ <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="ml-1 rounded border border-slate-200 px-2 py-1 text-sm" /></label>
            <button onClick={baseline} className="rounded-lg border border-brand px-3 py-1.5 text-sm font-semibold text-brand hover:bg-brand/5">Tạo phiên bản nền từ file Excel</button>
          </div>
        )}
      </div>

      {msg && <div className={`rounded-xl border p-3 text-sm ${msg.ok ? "border-green-200 bg-green-50 text-green-800" : "border-red-200 bg-red-50 text-red-700"}`}>{msg.text}</div>}

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full min-w-[960px] text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
              <th className="px-4 py-3">So sánh</th>
              <th>Phiên bản</th>
              <th>Trạng thái</th>
              <th>Recheck</th>
              <th className="text-right">Dòng</th>
              <th>Người tạo</th>
              <th>Ghi chú</th>
              <th className="px-4 text-right">Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((v) => (
              <tr key={v.id} className="border-b border-slate-50">
                <td className="px-4 py-2.5"><input type="checkbox" checked={pick.includes(v.id)} onChange={() => toggle(v.id)} aria-label={`Chọn ${v.code} để so sánh`} /></td>
                <td className={`font-mono text-xs font-semibold text-slate-800 ${v.minor !== null ? "pl-6" : ""}`}>
                  {v.minor !== null && <span className="mr-1 text-slate-300">└</span>}
                  {v.code}
                </td>
                <td><span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${STATUS_CLS[v.status]}`}>{v.status}</span></td>
                <td>
                  {v.recheck_result ? <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${RESULT_CLS[v.recheck_result]}`}>{v.recheck_result}</span> : "—"}
                  {v.recheck_summary?.counts && <span className="ml-1 text-[11px] text-slate-400">{v.recheck_summary.counts.ERROR}E · {v.recheck_summary.counts.WARNING}W</span>}
                </td>
                <td className="text-right">{v.row_count.toLocaleString("vi-VN")}</td>
                <td className="text-xs">{v.created_by}<br /><span className="text-slate-400">{dateTimeVi(v.created_at)}</span></td>
                <td className="max-w-[240px] truncate text-xs text-slate-500" title={v.note}>{v.note}</td>
                <td className="px-4 text-right">
                  <div className="flex justify-end gap-2">
                    {can("planning.recheck") && (
                      <button onClick={() => doRecheck(v)} disabled={busy === v.id} className="rounded-lg border border-slate-200 px-2.5 py-1 text-xs hover:bg-slate-50 disabled:opacity-50">
                        {busy === v.id ? "..." : "Recheck"}
                      </button>
                    )}
                    {can("planning.issue") && v.status === "COMMITTED" && (
                      <button onClick={() => doIssue(v)} className="rounded-lg bg-brand px-2.5 py-1 text-xs font-semibold text-white hover:bg-indigo-700">Issue</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {ordered.length === 0 && (
              <tr><td colSpan={8} className="py-8 text-center text-slate-400">Chưa có phiên bản nào.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center gap-3">
        <button onClick={compare} disabled={pick.length !== 2} className="rounded-lg bg-slate-800 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">So sánh 2 phiên bản đã chọn</button>
        <span className="text-xs text-slate-400">{pick.length}/2 đã chọn (tick ở cột đầu)</span>
      </div>

      {diff && (
        <Section title={`So sánh ${diff.a.code} → ${diff.b.code}`} subtitle={`${diff.total_changes.toLocaleString("vi-VN")} thay đổi${diff.truncated ? " (chỉ hiển thị phần đầu)" : ""}`}>
          <div className="mb-3 flex flex-wrap gap-2">
            {Object.entries(diff.summary).map(([k, n]) => (
              <span key={k} className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">{CATEGORY_LABEL[k] ?? k}: <b>{n}</b></span>
            ))}
            {diff.total_changes === 0 && <span className="text-sm text-slate-500">Hai phiên bản giống nhau.</span>}
          </div>
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-slate-100 text-slate-400"><th className="py-2">Loại</th><th>PO</th><th>Trường</th><th>Trước</th><th>Sau</th></tr>
              </thead>
              <tbody>
                {diff.changes.map((c, i) => (
                  <tr key={i} className="border-b border-slate-50">
                    <td className="py-1.5 font-semibold text-slate-700">{CATEGORY_LABEL[c.category] ?? c.category}</td>
                    <td>{c.po_number || c.row_uid}</td>
                    <td className="font-mono">{c.field}</td>
                    <td className="text-red-600">{show(c.before)}</td>
                    <td className="text-green-700">{show(c.after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
    </div>
  );
}
