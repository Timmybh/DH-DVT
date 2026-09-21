import { useCallback, useEffect, useState } from "react";
import { Navigate, NavLink, useParams, useSearchParams } from "react-router-dom";
import { api, errorMessage } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { dateVi, num } from "../../lib/format";

const SECTIONS = [
  { key: "plan-vs-actual", label: "Kế hoạch so với thực tế" },
  { key: "exceptions", label: "Ngoại lệ mapping" },
  { key: "history", label: "Lịch sử thực tế" },
];

const PAGE = 100;
const select = "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";
const th = "px-3 py-2 text-left text-[11px] font-bold uppercase text-slate-400";
const td = "px-3 py-1.5 whitespace-nowrap";

const PVA_STATUS: Record<string, { label: string; cls: string }> = {
  NO_ACTUAL: { label: "Chưa có thực tế", cls: "bg-slate-500/20 text-slate-400" },
  NOT_STARTED: { label: "Chưa may", cls: "bg-slate-500/20 text-slate-500" },
  IN_PROGRESS: { label: "Đang may", cls: "bg-sky-500/20 text-sky-600" },
  SEWN_COMPLETE: { label: "May xong", cls: "bg-indigo-500/20 text-indigo-600" },
  FG_COMPLETE: { label: "Đã nhập kho TP", cls: "bg-green-500/20 text-green-600" },
};
const MAP_STATUS: Record<string, { label: string; cls: string }> = {
  MATCHED: { label: "Tự động liên kết", cls: "bg-green-500/20 text-green-600" },
  REVIEW: { label: "Cần xác nhận", cls: "bg-amber-500/20 text-amber-600" },
  UNMATCHED: { label: "Chưa liên kết", cls: "bg-red-500/20 text-red-500" },
  OUT_OF_PLAN: { label: "Loại khỏi mapping (trước kỳ KH)", cls: "bg-slate-500/20 text-slate-500" },
  IGNORED: { label: "Loại khỏi mapping", cls: "bg-slate-500/20 text-slate-400" },
};
const GRADE: Record<string, string> = { EXACT: "Khớp chính xác", STRONG: "Ứng viên mạnh", POSSIBLE: "Ứng viên có thể", CONFIRM: "Cần xác nhận", "": "" };
const METHOD: Record<string, string> = { AUTO_FULL: "PO+Style+KH", AUTO_STYLE: "PO+Style", AUTO_PO: "Chỉ PO", AUTO_STYLE_WINDOW: "Style+chuyền+thời gian", MANUAL: "Gán tay", IGNORED: "Bỏ qua", "": "—" };

const Badge = ({ map, k }: { map: Record<string, { label: string; cls: string }>; k: string }) => (
  <span className={`pg-chip ${map[k]?.cls ?? ""}`}>{map[k]?.label ?? k}</span>
);

interface Pva {
  row_uid: string; po: string; style: string; customer: string; factory_code: string; line: string; planned_qty: number; sewn_qty: number; fg_qty: number;
  planned_end: string | null; planned_warehouse: string | null; sewn_done_date: string | null; fg_done_date: string | null; mappings: number; review: boolean; status: string;
  sewn_pct: number | null; fg_pct: number | null; sewn_delay_days: number | null; fg_delay_days: number | null; overdue: boolean;
}

function Pager({ total, offset, setOffset }: { total: number; offset: number; setOffset: (n: number) => void }) {
  if (total <= PAGE) return null;
  return (
    <div className="flex items-center gap-2 text-xs text-slate-500">
      <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="rounded-lg border border-slate-200 px-3 py-1 disabled:opacity-40">‹ Trước</button>
      <span>{num(offset + 1)}–{num(Math.min(offset + PAGE, total))} / {num(total)}</span>
      <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)} className="rounded-lg border border-slate-200 px-3 py-1 disabled:opacity-40">Sau ›</button>
    </div>
  );
}

const delay = (d: number | null) => (d === null ? "" : d > 0 ? ` (trễ ${d}n)` : d < 0 ? ` (sớm ${-d}n)` : " (đúng hạn)");

// ---------------------------------------------------------------- Plan vs Actual
function PlanVsActual() {
  const [data, setData] = useState<{ version: { code: string; status: string } | null; counts: Record<string, number>; total: number; rows: Pva[] } | null>(null);
  const [status, setStatus] = useState("");
  const [factory, setFactory] = useState("");
  const [q, setQ] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    const r = await api.get("/planning/actual/plan-vs-actual", { params: { status: status || undefined, factory: factory || undefined, q: q || undefined, overdue: overdue || undefined, limit: PAGE, offset } });
    setData(r.data);
  }, [status, factory, q, overdue, offset]);
  useEffect(() => {
    const t = setTimeout(() => load().catch((e) => setErr(errorMessage(e))), 200);
    return () => clearTimeout(t);
  }, [load]);
  useEffect(() => setOffset(0), [status, factory, q, overdue]);

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        So từng dòng kế hoạch của phiên bản tham chiếu{data?.version ? <> (<b>{data.version.code}</b> · {data.version.status})</> : ""} với thực tế eGMF đã mapping. May xong và nhập kho thành phẩm là hai mốc tách biệt;
        tiến độ tính theo số lượng thực tế, không chỉ ngày kế hoạch. Thực tế của nhiều PO cùng mã hàng được cộng vào dòng kế hoạch tương ứng.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={select} aria-label="Trạng thái">
          <option value="">Mọi trạng thái</option>
          {Object.entries(PVA_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}{data ? ` (${data.counts[k] ?? 0})` : ""}</option>)}
        </select>
        <select value={factory} onChange={(e) => setFactory(e.target.value)} className={select} aria-label="Xí nghiệp"><option value="">Mọi XN</option>{["XN1", "XN2", "XN3"].map((f) => <option key={f}>{f}</option>)}</select>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm PO / mã hàng / khách..." className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm" aria-label="Tìm" />
        <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={overdue} onChange={(e) => setOverdue(e.target.checked)} /> Quá hạn chưa may xong</label>
        <span className="flex-1" />
        <Pager total={data?.total ?? 0} offset={offset} setOffset={setOffset} />
      </div>
      {err && <p className="rounded-lg border border-red-300/50 px-3 py-2 text-sm text-red-700">{err}</p>}
      <div className="overflow-x-auto rounded-2xl border border-slate-200">
        <table className="w-full text-sm" data-testid="pva-table">
          <thead><tr><th className={th}>XN</th><th className={th}>Chuyền</th><th className={th}>PO</th><th className={th}>Mã hàng</th><th className={`${th} text-right`}>SL KH</th><th className={`${th} text-right`}>May xong</th><th className={`${th} text-right`}>Nhập kho</th><th className={th}>Kết thúc KH</th><th className={th}>May xong TT</th><th className={th}>Nhập kho TT</th><th className={th}>Trạng thái</th></tr></thead>
          <tbody>
            {data?.rows.map((r) => (
              <tr key={r.row_uid} className="border-t border-slate-100">
                <td className={td}>{r.factory_code}</td><td className={td}>{r.line}</td>
                <td className={td} title={r.customer}>{r.po || "—"}</td><td className={td}>{r.style}</td>
                <td className={`${td} text-right`}>{num(r.planned_qty)}</td>
                <td className={`${td} text-right`}>{num(r.sewn_qty)}{r.sewn_pct !== null && r.mappings ? <span className="ml-1 text-xs text-slate-400">{r.sewn_pct}%</span> : null}</td>
                <td className={`${td} text-right`}>{num(r.fg_qty)}{r.fg_pct !== null && r.mappings ? <span className="ml-1 text-xs text-slate-400">{r.fg_pct}%</span> : null}</td>
                <td className={td}>{dateVi(r.planned_end)}{r.overdue && <span className="ml-1 font-bold text-red-500" title="Quá hạn kế hoạch, chưa may xong">!</span>}</td>
                <td className={td}>{r.sewn_done_date ? `${dateVi(r.sewn_done_date)}${delay(r.sewn_delay_days)}` : "—"}</td>
                <td className={td}>{r.fg_done_date ? `${dateVi(r.fg_done_date)}${delay(r.fg_delay_days)}` : "—"}</td>
                <td className={td}><Badge map={PVA_STATUS} k={r.status} />{r.review && <span className="pg-chip bg-amber-500/20 text-amber-600" title="Có mapping cần xác nhận">?</span>}</td>
              </tr>
            ))}
            {data && data.rows.length === 0 && <tr><td colSpan={11} className="px-3 py-6 text-center text-slate-400">Không có dòng nào.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Ngoại lệ mapping
interface Mapping {
  id: number; po: string; style: string; customer: string; factory_code: string; line: string; status: string; method: string; grade: string; mapped_so_id: number | null; reason: string;
  candidates: string[]; mapped_row_uid: string | null; attrs: { qty?: number; sewn_qty?: number; fg_qty?: number; last_seen?: string | null }; reconciled_by: string;
}
interface Cand { row_uid: string; po: string; style: string; customer: string; factory_code: string; line: string; quantity: number; begin: string | null; end: string | null; so_number: string; so_description: string; reasons: string[]; date_gap_days: number | null }
interface Hist { id: number; action: string; old_row_uid: string | null; new_row_uid: string | null; old_status: string; new_status: string; reason: string; changed_by: string; changed_at: string | null }

function Exceptions({ canManage }: { canManage: boolean }) {
  const [summary, setSummary] = useState<{ version: { code: string } | null; mappings: Record<string, number>; observations: number; last_run: { code: string; at: string } | null } | null>(null);
  const [status, setStatus] = useState("REVIEW");
  const [factory, setFactory] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; rows: Mapping[] }>({ total: 0, rows: [] });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [pick, setPick] = useState<{ m: Mapping; cands: Cand[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [pq, setPq] = useState("");
  const [preason, setPreason] = useState("");
  const [hist, setHist] = useState<{ m: Mapping; rows: Hist[] } | null>(null);

  const load = useCallback(async () => {
    const [s, l] = await Promise.all([
      api.get("/planning/actual/summary"),
      api.get("/planning/actual/mappings", { params: { status: status || undefined, factory: factory || undefined, q: q || undefined, limit: PAGE, offset } }),
    ]);
    setSummary(s.data);
    setData(l.data);
  }, [status, factory, q, offset]);
  useEffect(() => {
    const t = setTimeout(() => load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })), 200);
    return () => clearTimeout(t);
  }, [load]);
  useEffect(() => setOffset(0), [status, factory, q]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  };
  const searchCands = async (m: Mapping, term: string) => {
    try {
      const r = await api.get<Cand[]>(`/planning/actual/mappings/${m.id}/candidates`, { params: { q: term || undefined } });
      setPick({ m, cands: r.data });
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };
  const openPick = async (m: Mapping) => {
    setPq("");
    setPreason("");
    await searchCands(m, "");
  };
  // Mọi thao tác tay đều cần lý do (spec §30) và được ghi lịch sử
  const withReason = (m: Mapping, path: "ignore" | "reset", ok: string) => {
    const reason = window.prompt(path === "ignore" ? "Lý do loại khỏi mapping?" : "Lý do đặt lại mapping?");
    if (!reason || reason.trim().length < 3) return;
    void act(() => api.post(`/planning/actual/mappings/${m.id}/${path}`, { reason: reason.trim() }), ok);
  };
  const openHist = async (m: Mapping) => {
    try {
      setHist({ m, rows: (await api.get<Hist[]>(`/planning/actual/mappings/${m.id}/history`)).data });
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">
        Thực tế eGMF được khớp với phiên bản kế hoạch tham chiếu{summary?.version ? <> (<b>{summary.version.code}</b>)</> : ""} theo khóa nghiệp vụ (PO + Style/CC + Khách hàng; không dùng ID nội bộ eGMF, không dùng số lượng).
        Kế hoạch hiện có phần lớn là dòng dự báo không có PO thật nên hệ thống còn khớp theo Style/CC + xí nghiệp + chuyền + cửa sổ thời gian; khi gán tay có thể chọn bất kỳ dòng nào (kèm lý do, có lịch sử). Mapping gán tay hoặc bỏ qua được giữ nguyên qua các lần đồng bộ.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {Object.entries(MAP_STATUS).map(([k, v]) => (
          <button key={k} onClick={() => setStatus(status === k ? "" : k)} aria-pressed={status === k} className={`rounded-full border px-3 py-1 text-xs font-semibold ${status === k ? "border-brand bg-indigo-500/20" : "border-slate-200"}`} data-testid={`map-filter-${k}`}>
            {v.label} <span className="ml-1 text-slate-400">{num(summary?.mappings[k] ?? 0)}</span>
          </button>
        ))}
        <span className="flex-1" />
        {summary?.last_run && <span className="text-xs text-slate-400">Đồng bộ gần nhất {summary.last_run.code} · {num(summary.observations)} quan sát</span>}
        {canManage && <button disabled={busy} onClick={() => act(() => api.post("/planning/actual/reconcile"), "Đã đối soát lại toàn bộ thực tế với phiên bản tham chiếu.")} className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-50" data-testid="reconcile-btn">Đối soát lại</button>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <select value={factory} onChange={(e) => setFactory(e.target.value)} className={select} aria-label="Xí nghiệp"><option value="">Mọi XN</option>{["XN1", "XN2", "XN3"].map((f) => <option key={f}>{f}</option>)}</select>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm PO / mã hàng / khách..." className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm" aria-label="Tìm" />
        <span className="flex-1" />
        <Pager total={data.total} offset={offset} setOffset={setOffset} />
      </div>
      {msg && <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}
      <div className="overflow-x-auto rounded-2xl border border-slate-200">
        <table className="w-full text-sm" data-testid="mapping-table">
          <thead><tr><th className={th}>PO (eGMF)</th><th className={th}>Mã hàng</th><th className={th}>XN</th><th className={th}>Chuyền</th><th className={`${th} text-right`}>SL</th><th className={`${th} text-right`}>May xong</th><th className={`${th} text-right`}>Nhập kho</th><th className={th}>Thấy lần cuối</th><th className={th}>Trạng thái</th><th className={th}>Cách khớp</th><th className={th}>Lý do</th>{canManage && <th className={th} />}</tr></thead>
          <tbody>
            {data.rows.map((m) => (
              <tr key={m.id} className="border-t border-slate-100 align-top">
                <td className={td} title={m.customer}>{m.po}</td><td className={td}>{m.style}</td><td className={td}>{m.factory_code}</td><td className={td}>{m.line}</td>
                <td className={`${td} text-right`}>{num(m.attrs.qty)}</td><td className={`${td} text-right`}>{num(m.attrs.sewn_qty)}</td><td className={`${td} text-right`}>{num(m.attrs.fg_qty)}</td>
                <td className={td}>{dateVi(m.attrs.last_seen)}</td>
                <td className={td}><Badge map={MAP_STATUS} k={m.status} /></td>
                <td className={td}>{METHOD[m.method] ?? m.method}{m.grade ? <span className="ml-1 text-xs text-slate-400">· {GRADE[m.grade]}</span> : null}</td>
                <td className="max-w-[340px] px-3 py-1.5 text-xs text-slate-500">{m.reason}{m.reconciled_by && m.method === "MANUAL" ? ` — ${m.reconciled_by}` : ""}</td>
                {canManage && (
                  <td className={`${td} text-right`}>
                    <button disabled={busy} onClick={() => openPick(m)} className="rounded-full border border-slate-300 px-3 py-1 text-xs" data-testid={`map-pick-${m.id}`}>Gán dòng KH</button>
                    {m.status !== "IGNORED" && <button disabled={busy} onClick={() => withReason(m, "ignore", "Đã loại bản ghi khỏi mapping.")} className="ml-1 rounded-full border border-slate-300 px-3 py-1 text-xs">Loại khỏi mapping</button>}
                    {(m.method === "MANUAL" || m.status === "IGNORED") && <button disabled={busy} onClick={() => withReason(m, "reset", "Đã bỏ quyết định tay, hệ thống khớp lại tự động.")} className="ml-1 rounded-full border border-slate-300 px-3 py-1 text-xs">Đặt lại</button>}
                    <button onClick={() => openHist(m)} className="ml-1 rounded-full border border-slate-300 px-3 py-1 text-xs">Lịch sử</button>
                  </td>
                )}
              </tr>
            ))}
            {data.rows.length === 0 && <tr><td colSpan={12} className="px-3 py-6 text-center text-slate-400">Không có bản ghi.</td></tr>}
          </tbody>
        </table>
      </div>

      {hist && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" onClick={() => setHist(null)}>
          <div className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 text-slate-900 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-bold">Lịch sử mapping — PO {hist.m.po}</h3>
            <ul className="mt-3 space-y-2 text-sm">
              {hist.rows.map((h) => (
                <li key={h.id} className="rounded-lg border border-slate-200 p-2">
                  <b>{h.action === "MAP" ? "Gán tay" : h.action === "IGNORE" ? "Loại khỏi mapping" : "Đặt lại"}</b> · {h.changed_by} · {h.changed_at ? dateVi(h.changed_at.slice(0, 10)) : ""}
                  <div className="text-xs text-slate-500">{h.old_row_uid ?? "—"} ({h.old_status}) → {h.new_row_uid ?? "—"} ({h.new_status})</div>
                  <div className="text-xs">Lý do: {h.reason}</div>
                </li>
              ))}
              {hist.rows.length === 0 && <li className="text-xs text-slate-400">Chưa có thay đổi tay.</li>}
            </ul>
          </div>
        </div>
      )}

      {pick && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" onClick={() => setPick(null)}>
          <div className="max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-6 text-slate-900 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-bold">Gán thực tế vào dòng kế hoạch</h3>
            <p className="mt-1 text-xs text-slate-500">PO {pick.m.po} · {pick.m.style} · {pick.m.customer} · {pick.m.factory_code}/{pick.m.line} — gán được vào bất kỳ dòng kế hoạch nào (PO chỉ là một tín hiệu gợi ý).</p>
            <div className="mt-2 flex gap-2">
              <input value={pq} onChange={(e) => setPq(e.target.value)} onKeyDown={(e) => e.key === "Enter" && searchCands(pick.m, pq)} placeholder="Tìm theo PO / Style / Customer / SO..." className="flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-sm" aria-label="Tìm dòng kế hoạch" />
              <button onClick={() => searchCands(pick.m, pq)} className="rounded-full border border-slate-300 px-4 py-1 text-xs">Tìm</button>
            </div>
            <input value={preason} onChange={(e) => setPreason(e.target.value)} placeholder="Lý do gán tay (bắt buộc)" className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm" aria-label="Lý do" data-testid="map-reason" />
            {pick.cands.length === 0 ? (
              <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">Không có dòng kế hoạch phù hợp. Hãy thử tìm theo PO / Style / Customer / SO khác, hoặc chọn "Loại khỏi mapping".</p>
            ) : (
              <table className="mt-3 w-full text-sm">
                <thead><tr><th className={th}>SO</th><th className={th}>PO</th><th className={th}>XN</th><th className={th}>Chuyền</th><th className={th}>Mã hàng</th><th className={`${th} text-right`}>SL</th><th className={th}>Bắt đầu</th><th className={th}>Kết thúc</th><th className={th}>Gợi ý</th><th className={th} /></tr></thead>
                <tbody>
                  {pick.cands.map((c) => (
                    <tr key={c.row_uid} className={`border-t border-slate-100 ${pick.m.mapped_row_uid === c.row_uid ? "bg-indigo-50" : ""}`}>
                      <td className={`${td} font-mono text-[11px]`} title={c.so_description}>{c.so_number}</td><td className={td}>{c.po}</td><td className={td}>{c.factory_code}</td><td className={td}>{c.line}</td><td className={td}>{c.style}</td><td className={`${td} text-right`}>{num(c.quantity)}</td><td className={td}>{dateVi(c.begin)}</td><td className={td}>{dateVi(c.end)}</td>
                      <td className="px-3 text-xs text-green-700">{c.reasons.map((r) => `✓ ${r}`).join(" ")}{c.date_gap_days ? ` · lệch ${c.date_gap_days} ngày` : ""}</td>
                      <td className={td}><button onClick={() => act(() => api.post(`/planning/actual/mappings/${pick.m.id}/map`, { row_uid: c.row_uid, reason: preason }), "Đã gán tay — sẽ được giữ qua các lần đồng bộ.").then(() => setPick(null))} disabled={preason.trim().length < 3} className="rounded-full bg-brand disabled:opacity-40 px-3 py-1 text-xs font-semibold text-white" data-testid={`map-to-${c.row_uid}`}>Gán</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="mt-4 text-right"><button onClick={() => setPick(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Đóng</button></div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Lịch sử thực tế
interface Obs {
  id: number; actual_key: string; sync_run_id: number; observed_at: string | null; po: string; style: string; factory_code: string; line: string; qty: number; sewn_qty: number; fg_qty: number;
  is_new: boolean; changes: Record<string, unknown>;
}
interface RunRow { run_id: number; code: string; at: string | null; observations: number; new: number; changed: number }

const FIELD_LABEL: Record<string, string> = { qty: "SL", sewn_qty: "May xong", fg_qty: "Nhập kho", due_date: "Hạn giao", sewn_done_date: "Ngày may xong", fg_done_date: "Ngày nhập kho đủ", customer: "Khách", style: "Mã hàng" };
const fmtChange = (c: Record<string, unknown>): string =>
  c._new ? "Xuất hiện lần đầu" : Object.entries(c).map(([k, v]) => `${FIELD_LABEL[k] ?? k}: ${(v as unknown[]).map((x) => (x === null || x === "" ? "—" : String(x))).join(" → ")}`).join(" · ");

function History() {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [changes, setChanges] = useState<{ total: number; new: number; rows: Obs[] } | null>(null);
  const [params] = useSearchParams();
  const [po, setPo] = useState(params.get("po") ?? "");
  const [hist, setHist] = useState<Obs[] | null>(null);
  const [state, setState] = useState<Obs[] | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (params.get("po")) search(params.get("po") as string); // đến từ drill-down Dashboard: tự tra cứu PO
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);
  useEffect(() => {
    api.get<RunRow[]>("/planning/actual/runs").then((r) => setRuns(r.data)).catch((e) => setErr(errorMessage(e)));
  }, []);
  useEffect(() => {
    if (runId === null) return;
    api.get(`/planning/actual/runs/${runId}/changes`, { params: { limit: 300 } }).then((r) => setChanges(r.data)).catch((e) => setErr(errorMessage(e)));
  }, [runId]);

  const search = async (value = po) => {
    if (!value.trim()) return;
    setErr("");
    try {
      setHist((await api.get<Obs[]>("/planning/actual/history", { params: { po: value.trim() } })).data);
      setState(runId !== null ? (await api.get<Obs[]>("/planning/actual/state", { params: { run_id: runId, po: value.trim() } })).data : null);
    } catch (e) {
      setErr(errorMessage(e));
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">Mỗi lần đồng bộ chỉ ghi thực tế MỚI hoặc THAY ĐỔI, không ghi đè trạng thái cũ. Có thể xem thực tế tại lần đồng bộ N, thay đổi giữa hai lần, và thời điểm số lượng/ngày/trạng thái đổi.</p>
      {err && <p className="rounded-lg border border-red-300/50 px-3 py-2 text-sm text-red-700">{err}</p>}
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <div className="rounded-2xl border border-slate-200 p-3">
          <p className="mb-2 text-xs font-bold uppercase text-slate-400">Các lần đồng bộ</p>
          <div className="max-h-[60vh] space-y-1 overflow-y-auto" data-testid="actual-runs">
            {runs.map((r) => (
              <button key={r.run_id} onClick={() => setRunId(r.run_id)} aria-pressed={runId === r.run_id} className={`w-full rounded-lg border px-3 py-2 text-left text-xs ${runId === r.run_id ? "border-brand bg-indigo-500/20" : "border-slate-200"}`}>
                <b>{r.code}</b><br /><span className="text-slate-500">{r.at ? new Date(r.at).toLocaleString("vi-VN") : ""} · {num(r.new)} mới · {num(r.changed)} đổi</span>
              </button>
            ))}
            {runs.length === 0 && <p className="text-xs text-slate-400">Chưa có lần đồng bộ nào ghi thực tế.</p>}
          </div>
        </div>
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <input value={po} onChange={(e) => setPo(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} placeholder="Nhập PO để xem lịch sử..." className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm" aria-label="PO" data-testid="history-po" />
            <button onClick={() => search()} className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white">Xem lịch sử</button>
            {runId !== null && <span className="text-xs text-slate-400">Trạng thái tại lần đã chọn sẽ hiện kèm khi tìm PO.</span>}
          </div>
          {hist && (
            <div className="overflow-x-auto rounded-2xl border border-slate-200" data-testid="history-table">
              <table className="w-full text-sm">
                <thead><tr><th className={th}>Lần đồng bộ</th><th className={th}>XN/Chuyền</th><th className={`${th} text-right`}>May xong</th><th className={`${th} text-right`}>Nhập kho</th><th className={th}>Thay đổi</th></tr></thead>
                <tbody>
                  {hist.map((o) => (
                    <tr key={o.id} className="border-t border-slate-100"><td className={td}>{runs.find((r) => r.run_id === o.sync_run_id)?.code ?? o.sync_run_id}</td><td className={td}>{o.factory_code}/{o.line}</td><td className={`${td} text-right`}>{num(o.sewn_qty)}</td><td className={`${td} text-right`}>{num(o.fg_qty)}</td><td className="px-3 py-1.5 text-xs text-slate-500">{fmtChange(o.changes)}</td></tr>
                  ))}
                  {hist.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-slate-400">Không có lịch sử cho PO này.</td></tr>}
                </tbody>
              </table>
            </div>
          )}
          {state && state.length > 0 && <p className="text-xs text-slate-500">Tại lần đã chọn: {state.map((s) => `${s.factory_code}/${s.line}: may xong ${num(s.sewn_qty)}, nhập kho ${num(s.fg_qty)}`).join(" · ")}</p>}
          {changes && (
            <div className="overflow-x-auto rounded-2xl border border-slate-200" data-testid="run-changes">
              <p className="px-3 py-2 text-xs text-slate-500">{num(changes.total)} bản ghi mới hoặc thay đổi ({num(changes.new)} mới){changes.total > changes.rows.length ? ` — hiện ${changes.rows.length} dòng đầu` : ""}</p>
              <table className="w-full text-sm">
                <thead><tr><th className={th}>PO</th><th className={th}>Mã hàng</th><th className={th}>XN/Chuyền</th><th className={th}>Thay đổi</th></tr></thead>
                <tbody>{changes.rows.map((o) => <tr key={o.id} className="border-t border-slate-100"><td className={td}>{o.po}</td><td className={td}>{o.style}</td><td className={td}>{o.factory_code}/{o.line}</td><td className="px-3 py-1.5 text-xs text-slate-500">{fmtChange(o.changes)}</td></tr>)}</tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Actual() {
  const { section } = useParams();
  const { can } = useAuth();
  const current = SECTIONS.find((s) => s.key === section);
  if (!current) return <Navigate to="/planning/actual/plan-vs-actual" replace />;
  return (
    <div className="space-y-4">
      <nav className="flex gap-1 border-b border-slate-200">
        {SECTIONS.map((s) => (
          <NavLink key={s.key} to={`/planning/actual/${s.key}`} className={({ isActive }) => `-mb-px border-b-2 px-4 py-2 text-sm font-medium ${isActive ? "border-brand text-brand" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{s.label}</NavLink>
        ))}
      </nav>
      {current.key === "plan-vs-actual" && <PlanVsActual />}
      {current.key === "exceptions" && <Exceptions canManage={can("mapping.manage")} />}
      {current.key === "history" && <History />}
    </div>
  );
}
