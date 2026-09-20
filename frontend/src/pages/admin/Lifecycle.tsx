import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { dateTimeVi, num } from "../../lib/format";

interface Check { code: string; ok: boolean; blocking: boolean; message: string }
interface CF {
  id: number; year: number; status: string; source_version_id: number; target_version_id: number | null; created_by: string; created_at: string | null; applied_at: string | null;
  summary: Record<string, unknown>; report: Check[];
}
interface CFDetail extends CF { total_items: number; items: { row_uid: string; factory_code: string; line: string; po: string; style: string; planned_qty: number; fg_qty: number; remaining_qty: number; planned_end: string | null; has_transfer: boolean; reason: string }[] }
interface YearRow { year: number; counts: Record<string, number>; carry_forward: CF | null; archive: { status: string; created_at: string; path: string; rows: number } | null; past: boolean; due_by_policy: boolean }
interface Overview { current_year: number; retention_online_years: number; years: YearRow[]; note: string }

const LABEL: Record<string, string> = { planning_versions: "Phiên bản KH", actual_observations: "Quan sát thực tế", sync_runs: "Lần đồng bộ", qa_defect_daily: "QA theo ngày", labor_daily: "Lao động theo ngày" };
const CF_BADGE: Record<string, string> = { DRAFT: "bg-slate-500/20 text-slate-500", VALIDATED: "bg-green-500/20 text-green-600", FAILED: "bg-red-500/20 text-red-500", APPLIED: "bg-indigo-500/20 text-indigo-500" };
const th = "px-3 py-2 text-left text-[11px] font-bold uppercase text-slate-400";

export default function Lifecycle() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<CFDetail | null>(null);
  const [includeNo, setIncludeNo] = useState(true);
  const [arch, setArch] = useState<{ year: number; tables: Record<string, number>; path: string } | null>(null);
  const [confirm, setConfirm] = useState("");

  const load = useCallback(() => api.get<Overview>("/admin/lifecycle/overview").then((r) => setOv(r.data)).catch((e) => setMsg({ ok: false, text: errorMessage(e) })), []);
  useEffect(() => { load(); }, [load]);

  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    try {
      setMsg({ ok: true, text: await fn() });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  };
  const openDetail = async (id: number) => setDetail((await api.get<CFDetail>(`/admin/lifecycle/carry-forward/${id}`)).data);

  return (
    <div className="space-y-4" data-testid="lifecycle">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Vòng đời năm</h1>
        <p className="text-xs text-slate-500">
          Cuối năm: <b>kết chuyển</b> các mục còn dở (số lượng còn lại, chuyển chuyền, mapping) → kiểm tra → <b>áp dụng</b> thành phiên bản đầu năm sau → mới được <b>lưu trữ</b> dữ liệu giao dịch/lịch sử của năm cũ ra tệp nén (có SHA-256, phục hồi được).
          {ov ? ` ${ov.note} Chính sách hiện tại: giữ online ${ov.retention_online_years} năm (tính cả năm hiện hành).` : ""}
        </p>
      </div>
      {msg && <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeNo} onChange={(e) => setIncludeNo(e.target.checked)} /> Kết chuyển cả các mục chưa có thực tế (kế hoạch / dự báo)</label>

      <div className="overflow-x-auto rounded-2xl border border-slate-200">
        <table className="w-full text-sm" data-testid="lifecycle-years">
          <thead><tr><th className={th}>Năm</th><th className={th}>Dữ liệu năm</th><th className={th}>Kết chuyển</th><th className={th}>Lưu trữ</th><th className={th} /></tr></thead>
          <tbody>
            {ov?.years.map((y) => {
              const cf = y.carry_forward;
              const archived = y.archive?.status === "ARCHIVED";
              return (
                <tr key={y.year} className="border-t border-slate-100 align-top">
                  <td className="px-3 py-2 font-bold">{y.year}{y.year === ov.current_year && <span className="ml-1 text-xs font-normal text-slate-400">(hiện hành)</span>}{y.past && y.due_by_policy && !archived && <span className="pg-chip ml-2 bg-amber-500/20 text-amber-600">quá hạn giữ online</span>}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{Object.entries(y.counts).map(([k, v]) => `${LABEL[k] ?? k}: ${num(v)}`).join(" · ")}</td>
                  <td className="px-3 py-2">
                    {cf ? <><span className={`pg-chip ${CF_BADGE[cf.status]}`}>{cf.status}</span><span className="text-xs text-slate-500"> {num(Number(cf.summary.carried ?? 0))} mục · còn lại {num(Number(cf.summary.remaining_qty ?? 0))}</span>
                      <button onClick={() => openDetail(cf.id)} className="ml-2 text-xs text-brand underline">Chi tiết</button></> : <span className="text-xs text-slate-400">Chưa kết chuyển</span>}
                  </td>
                  <td className="px-3 py-2 text-xs">{y.archive ? <><span className={`pg-chip ${archived ? "bg-slate-500/20 text-slate-500" : "bg-green-500/20 text-green-600"}`}>{y.archive.status}</span> {num(y.archive.rows)} bản ghi</> : <span className="text-slate-400">—</span>}</td>
                  <td className="px-3 py-2 text-right">
                    <button disabled={busy} onClick={() => run(async () => { const r = await api.post<CF>("/admin/lifecycle/carry-forward", { year: y.year, include_no_actual: includeNo }); await openDetail(r.data.id); return `Đã tạo bản kết chuyển ${y.year}: ${r.data.status}.`; })} className="rounded-full border border-slate-300 px-3 py-1 text-xs" data-testid={`cf-build-${y.year}`}>Tạo kết chuyển</button>
                    {cf?.status === "VALIDATED" && <button disabled={busy} onClick={() => window.confirm(`Áp dụng kết chuyển ${y.year}: tạo phiên bản đầu năm ${y.year + 1}?`) && run(async () => { const r = await api.post<{ code: string; rows: number; recheck: string }>(`/admin/lifecycle/carry-forward/${cf.id}/apply`); return `Đã tạo ${r.data.code}: ${num(r.data.rows)} dòng (Recheck ${r.data.recheck}).`; })} className="ml-1 rounded-full bg-brand px-3 py-1 text-xs font-semibold text-white">Áp dụng</button>}
                    {y.past && cf && ["VALIDATED", "APPLIED"].includes(cf.status) && !archived && <button disabled={busy} onClick={() => run(async () => { const r = await api.get(`/admin/lifecycle/archive/${y.year}/dry-run`); setArch({ year: y.year, ...r.data }); setConfirm(""); return `Xem trước lưu trữ ${y.year}: chưa xóa gì.`; })} className="ml-1 rounded-full border border-slate-300 px-3 py-1 text-xs" data-testid={`arch-plan-${y.year}`}>Lưu trữ…</button>}
                    {archived && <button disabled={busy} onClick={() => window.confirm(`Phục hồi dữ liệu năm ${y.year} từ tệp lưu trữ?`) && run(async () => { const r = await api.post<{ restored: Record<string, number> }>(`/admin/lifecycle/archive/${y.year}/restore`); return `Đã phục hồi: ${Object.entries(r.data.restored).map(([k, v]) => `${k} ${num(v)}`).join(", ")}.`; })} className="ml-1 rounded-full border border-slate-300 px-3 py-1 text-xs">Phục hồi</button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {detail && (
        <section className="rounded-2xl border border-slate-200 bg-white p-4" data-testid="cf-detail">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold">Kết chuyển năm {detail.year} · <span className={`pg-chip ${CF_BADGE[detail.status]}`}>{detail.status}</span></h3>
            <button onClick={() => setDetail(null)} className="text-slate-400">✕</button>
          </div>
          <p className="text-xs text-slate-500">Nguồn {String(detail.summary.source_version ?? "")} · {num(Number(detail.summary.source_rows ?? 0))} dòng · kết chuyển {num(Number(detail.summary.carried ?? 0))} · đã đóng {num(Number(detail.summary.closed ?? 0))} · SL còn lại {num(Number(detail.summary.remaining_qty ?? 0))}</p>
          <ul className="mt-3 space-y-1 text-sm">
            {detail.report.map((c) => <li key={c.code} className={c.ok ? "text-green-700" : c.blocking ? "font-semibold text-red-600" : "text-amber-600"}>{c.ok ? "✓" : c.blocking ? "✗" : "!"} {c.message}{!c.ok && c.blocking ? " (chặn)" : ""}</li>)}
          </ul>
          <div className="mt-3 max-h-72 overflow-auto rounded-lg border border-slate-100">
            <table className="w-full text-xs">
              <thead><tr><th className={th}>XN</th><th className={th}>Chuyền</th><th className={th}>PO</th><th className={th}>Mã hàng</th><th className={`${th} text-right`}>SL KH</th><th className={`${th} text-right`}>Nhập kho</th><th className={`${th} text-right`}>Còn lại</th><th className={th}>Ghi chú</th></tr></thead>
              <tbody>{detail.items.map((i) => <tr key={i.row_uid} className="border-t border-slate-100"><td className="px-3 py-1">{i.factory_code}</td><td className="px-3">{i.line}</td><td className="px-3">{i.po}</td><td className="px-3">{i.style}</td><td className="px-3 text-right">{num(i.planned_qty)}</td><td className="px-3 text-right">{num(i.fg_qty)}</td><td className="px-3 text-right font-semibold">{num(i.remaining_qty)}</td><td className="px-3 text-slate-500">{i.reason === "NO_ACTUAL" ? "chưa có thực tế" : "đang dở"}{i.has_transfer ? " · chuyển chuyền" : ""}</td></tr>)}</tbody>
            </table>
          </div>
          {detail.total_items > detail.items.length && <p className="mt-1 text-xs text-slate-400">Hiện {detail.items.length} / {num(detail.total_items)} mục.</p>}
        </section>
      )}

      {arch && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" onClick={() => setArch(null)}>
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 text-slate-900 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-bold">Lưu trữ dữ liệu năm {arch.year}</h3>
            <p className="mt-1 text-xs text-slate-500">Xuất ra <span className="break-all font-mono">{arch.path}</span>, đối chiếu số dòng + SHA-256 rồi mới xóa khỏi bảng nóng. Phiên bản đang Issue, trạng thái thực tế hiện tại và toàn bộ Master data được giữ nguyên.</p>
            <ul className="mt-3 space-y-1 text-sm">{Object.entries(arch.tables).map(([k, v]) => <li key={k} className="flex justify-between"><span>{k}</span><b>{num(v)}</b></li>)}</ul>
            <label className="mt-4 block text-xs text-slate-500">Gõ <b>ARCHIVE {arch.year}</b> để xác nhận
              <input value={confirm} onChange={(e) => setConfirm(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" aria-label="Xác nhận lưu trữ" data-testid="arch-confirm" />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setArch(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
              <button disabled={confirm !== `ARCHIVE ${arch.year}` || busy} onClick={() => run(async () => { const r = await api.post(`/admin/lifecycle/archive/${arch.year}`, { confirm }); setArch(null); return `Đã lưu trữ năm ${arch.year} vào ${r.data.path}.`; })} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="arch-run">Lưu trữ</button>
            </div>
          </div>
        </div>
      )}
      {ov && ov.years.length > 0 && <p className="text-xs text-slate-400">Cập nhật lúc {dateTimeVi(new Date().toISOString())}</p>}
    </div>
  );
}
