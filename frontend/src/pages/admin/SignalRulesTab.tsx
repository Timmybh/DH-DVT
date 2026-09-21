import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";

interface Level { id?: number; name: string; zone: "GOOD" | "WARN"; severity: "INFO" | "WARNING" | "CRITICAL"; tag: string; op: string; value_from: number; value_to: number | null; template: string }
interface Rule { id: number; code: string; name: string; metric_code: string; metric_name: string; unit: string; status: string; note: string; display_order: number; levels: Level[] }
interface Metric { code: string; name: string; unit: string; note: string }
interface Meta { metrics: Metric[]; placeholders: string[]; ops: string[] }
interface Preview { id: string; zone: string; severity: string; title: string; detail: string }

const inp = "w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";
const th = "px-2 py-1.5 text-left text-[11px] font-bold uppercase text-slate-400 whitespace-nowrap";
const ZONE = { GOOD: "Tin tốt", WARN: "Tin xấu / cảnh báo" };
const SEV = { INFO: "Thông tin", WARNING: "Cảnh báo (cam)", CRITICAL: "Nghiêm trọng (đỏ)" };
const OP_LABEL: Record<string, string> = { ">=": "≥", ">": ">", "<=": "≤", "<": "<", BETWEEN: "trong khoảng" };
const blank = (): Level => ({ name: "", zone: "GOOD", severity: "INFO", tag: "Tin tốt", op: ">=", value_from: 0, value_to: null, template: "{xn} ..." });

/** Điều kiện hiển thị của một cấp độ: "≥ 95", "< 90", "80 – 90". */
const cond = (l: Level) => (l.op === "BETWEEN" ? `${l.value_from} – ${l.value_to ?? "?"}` : `${OP_LABEL[l.op] ?? l.op} ${l.value_from}`);
/** Xem trước lời ghép với dữ liệu mẫu. */
const sample = (l: Level, unit: string) => {
  const ctx: Record<string, string> = { xn: "XN2", factory: "Xí nghiệp 2", value: String(l.op === "BETWEEN" ? l.value_from : l.value_from), tag: l.tag, metric: "chỉ số", unit };
  const msg = l.template.replace(/\{(\w+)\}/g, (_m, k: string) => ctx[k] ?? `{${k}}`);
  return l.tag ? `${l.tag}: ${msg}` : msg;
};

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="my-4 w-full max-w-5xl rounded-2xl bg-white p-6 text-slate-900 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between"><h3 className="text-lg font-bold">{title}</h3><button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Đóng">✕</button></div>
        {children}
      </div>
    </div>
  );
}

/** Bảng đăng ký Tin tốt / Tin xấu: chỉ số đo lường + các cấp độ (khoảng giá trị → vùng, mức độ, nhãn, lời ghép). */
export default function SignalRulesTab({ canManage }: { canManage: boolean }) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [meta, setMeta] = useState<Meta>({ metrics: [], placeholders: [], ops: [] });
  const [preview, setPreview] = useState<Preview[]>([]);
  const [edit, setEdit] = useState<{ id?: number; code: string; name: string; metric_code: string; note: string; levels: Level[] } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const [r, m, p] = await Promise.all([api.get<Rule[]>("/admin/dashboard/signal-rules"), api.get<Meta>("/admin/dashboard/signal-metrics"), api.get<Preview[]>("/admin/dashboard/signal-rules/preview")]);
    setRules(r.data); setMeta(m.data); setPreview(p.data);
  }, []);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: errorMessage(e) })); }, [load]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); setMsg({ ok: true, text: ok }); await load(); return true; } catch (e) { setMsg({ ok: false, text: errorMessage(e) }); return false; }
  };
  const save = async () => {
    if (!edit) return;
    const body = { name: edit.name, metric_code: edit.metric_code, note: edit.note, levels: edit.levels.map((l) => ({ ...l, value_to: l.op === "BETWEEN" ? l.value_to : null })) };
    const done = await act(() => (edit.id ? api.put(`/admin/dashboard/signal-rules/${edit.id}`, body) : api.post("/admin/dashboard/signal-rules", { ...body, code: edit.code })), "Đã lưu quy tắc.");
    if (done) setEdit(null);
  };
  const unitOf = (code: string) => meta.metrics.find((m) => m.code === code)?.unit ?? "";
  const patchLevel = (i: number, p: Partial<Level>) => setEdit((e) => (e ? { ...e, levels: e.levels.map((l, k) => (k === i ? { ...l, ...p } : l)) } : e));
  const moveLevel = (i: number, d: -1 | 1) => setEdit((e) => { if (!e) return e; const j = i + d; if (j < 0 || j >= e.levels.length) return e; const n = [...e.levels]; [n[i], n[j]] = [n[j], n[i]]; return { ...e, levels: n }; });

  return (
    <div className="space-y-4" data-testid="signal-rules-tab">
      <p className="text-xs text-slate-500">Đăng ký các <b>chỉ số đo lường</b> dùng để lên tin cho khối Tin tốt / Cảnh báo. Mỗi quy tắc có nhiều <b>cấp độ</b>: khoảng giá trị → vùng (Tin tốt hoặc Cảnh báo), mức độ, nhãn (ví dụ "Tin nóng") và <b>lời ghép</b>. Cấp độ được xét từ trên xuống, cấp đầu tiên khớp thì lên tin. Không xóa, chỉ Ngưng áp dụng.</p>
      {msg && <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}
      <div className="flex"><span className="flex-1" />{canManage && <button onClick={() => setEdit({ code: "", name: "", metric_code: meta.metrics[0]?.code ?? "", note: "", levels: [blank()] })} className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white" data-testid="signal-add">+ Quy tắc mới</button>}</div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-3">
          {rules.map((r) => (
            <section key={r.id} className={`rounded-2xl border border-slate-200 bg-white p-4 ${r.status === "INACTIVE" ? "opacity-60" : ""}`} data-testid={`signal-rule-${r.code}`}>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-bold text-slate-900">{r.name}</h3>
                <span className="text-xs text-slate-400">{r.code} · {r.metric_name} ({r.unit})</span>
                <span className={`pg-chip ${r.status === "ACTIVE" ? "pg-ok" : "bg-slate-500/20 text-slate-500"}`}>{r.status === "ACTIVE" ? "Đang dùng" : "Ngưng"}</span>
                <span className="flex-1" />
                {canManage && <>
                  <button onClick={() => setEdit({ id: r.id, code: r.code, name: r.name, metric_code: r.metric_code, note: r.note, levels: r.levels.map((l) => ({ ...l })) })} className="text-xs text-brand hover:underline">Sửa</button>
                  <button onClick={() => act(() => api.post(`/admin/dashboard/signal-rules/${r.id}/${r.status === "ACTIVE" ? "deactivate" : "activate"}`), r.status === "ACTIVE" ? "Đã ngưng quy tắc." : "Đã áp dụng lại.")} className="text-xs text-slate-500 hover:underline">{r.status === "ACTIVE" ? "Ngưng áp dụng" : "Áp dụng lại"}</button></>}
              </div>
              <table className="mt-2 w-full text-sm">
                <thead><tr><th className={th}>Điều kiện</th><th className={th}>Vùng</th><th className={th}>Mức độ</th><th className={th}>Lời ghép (ví dụ)</th></tr></thead>
                <tbody>
                  {r.levels.map((l, i) => (
                    <tr key={l.id ?? i} className="border-t border-slate-100">
                      <td className="whitespace-nowrap px-2 py-1 font-mono text-xs">{cond(l)}{r.unit === "%" ? "%" : ""}</td>
                      <td className="px-2"><span className={`pg-chip ${l.zone === "GOOD" ? "pg-ok" : "pg-late"}`}>{ZONE[l.zone]}</span></td>
                      <td className="px-2 text-xs">{SEV[l.severity]}</td>
                      <td className="px-2 text-xs">{sample(l, r.unit)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ))}
          {rules.length === 0 && <p className="text-sm text-slate-400">Chưa có quy tắc nào.</p>}
        </div>

        <aside className="rounded-2xl border border-slate-200 bg-white p-4" data-testid="signal-preview">
          <h3 className="text-sm font-bold text-slate-900">Tin đang được tạo từ các quy tắc</h3>
          <p className="mb-2 text-[11px] text-slate-400">Tính theo số liệu hiện tại của XN1, XN2, XN3.</p>
          <ul className="space-y-1.5">
            {preview.map((p) => (
              <li key={p.id} className={`rounded-lg border px-2 py-1.5 text-xs ${p.zone === "GOOD" ? "border-green-300/50" : p.severity === "CRITICAL" ? "border-red-300/60" : "border-amber-300/60"}`}>
                <p className="font-semibold">{p.title}</p><p className="text-[11px] text-slate-400">{p.detail}</p>
              </li>
            ))}
            {preview.length === 0 && <li className="text-xs text-slate-400">Chưa có tin nào khớp điều kiện.</li>}
          </ul>
        </aside>
      </div>

      {edit && (
        <Modal title={edit.id ? `Sửa quy tắc ${edit.code}` : "Quy tắc tin mới"} onClose={() => setEdit(null)}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="block text-xs text-slate-500">Mã quy tắc<input className={inp} disabled={!!edit.id} value={edit.code} onChange={(e) => setEdit({ ...edit, code: e.target.value.toUpperCase() })} placeholder="HIEU_SUAT" data-testid="signal-code" /></label>
            <label className="block text-xs text-slate-500">Tên<input className={inp} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} data-testid="signal-name" /></label>
            <label className="block text-xs text-slate-500">Chỉ số đo lường
              <select className={inp} value={edit.metric_code} onChange={(e) => setEdit({ ...edit, metric_code: e.target.value })} data-testid="signal-metric">{meta.metrics.map((m) => <option key={m.code} value={m.code}>{m.name} ({m.unit})</option>)}</select>
            </label>
          </div>
          <p className="mt-1 text-[11px] text-slate-400">{meta.metrics.find((m) => m.code === edit.metric_code)?.note}</p>

          <h4 className="mt-4 text-xs font-bold uppercase text-slate-400">Cấp độ (xét từ trên xuống)</h4>
          <div className="mt-1 overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm" data-testid="signal-levels">
              <thead><tr><th className={th}>Tên cấp</th><th className={th}>Vùng</th><th className={th}>Mức độ</th><th className={th}>Nhãn</th><th className={th}>So sánh</th><th className={th}>Từ</th><th className={th}>Đến</th><th className={th}>Lời ghép</th><th className={th} /></tr></thead>
              <tbody>
                {edit.levels.map((l, i) => (
                  <tr key={i} className="border-t border-slate-100 align-top">
                    <td className="px-1 py-1"><input className={inp} value={l.name} onChange={(e) => patchLevel(i, { name: e.target.value })} aria-label={`Tên cấp ${i + 1}`} /></td>
                    <td className="px-1 py-1"><select className={inp} value={l.zone} onChange={(e) => patchLevel(i, { zone: e.target.value as Level["zone"], severity: e.target.value === "GOOD" ? "INFO" : l.severity === "INFO" ? "WARNING" : l.severity })} aria-label={`Vùng cấp ${i + 1}`}>{Object.entries(ZONE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></td>
                    <td className="px-1 py-1"><select className={inp} value={l.severity} disabled={l.zone === "GOOD"} onChange={(e) => patchLevel(i, { severity: e.target.value as Level["severity"] })} aria-label={`Mức độ cấp ${i + 1}`}>{Object.entries(SEV).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></td>
                    <td className="px-1 py-1"><input className={inp} value={l.tag} onChange={(e) => patchLevel(i, { tag: e.target.value })} placeholder="Tin nóng" aria-label={`Nhãn cấp ${i + 1}`} /></td>
                    <td className="px-1 py-1"><select className={inp} value={l.op} onChange={(e) => patchLevel(i, { op: e.target.value })} aria-label={`So sánh cấp ${i + 1}`}>{meta.ops.map((o) => <option key={o} value={o}>{OP_LABEL[o] ?? o}</option>)}</select></td>
                    <td className="px-1 py-1"><input type="number" className={`${inp} w-20`} value={l.value_from} onChange={(e) => patchLevel(i, { value_from: Number(e.target.value) })} aria-label={`Giá trị từ cấp ${i + 1}`} /></td>
                    <td className="px-1 py-1"><input type="number" className={`${inp} w-20`} disabled={l.op !== "BETWEEN"} value={l.value_to ?? ""} onChange={(e) => patchLevel(i, { value_to: e.target.value === "" ? null : Number(e.target.value) })} aria-label={`Giá trị đến cấp ${i + 1}`} /></td>
                    <td className="px-1 py-1"><input className={`${inp} min-w-[260px]`} value={l.template} onChange={(e) => patchLevel(i, { template: e.target.value })} aria-label={`Lời ghép cấp ${i + 1}`} data-testid={`signal-template-${i}`} />
                      <p className="mt-0.5 text-[11px] text-slate-400">→ {sample(l, unitOf(edit.metric_code))}</p></td>
                    <td className="whitespace-nowrap px-1 py-1 text-xs">
                      <button onClick={() => moveLevel(i, -1)} disabled={i === 0} className="disabled:opacity-30" aria-label="Lên">↑</button>
                      <button onClick={() => moveLevel(i, 1)} disabled={i === edit.levels.length - 1} className="ml-1 disabled:opacity-30" aria-label="Xuống">↓</button>
                      <button onClick={() => setEdit({ ...edit, levels: edit.levels.filter((_, k) => k !== i) })} disabled={edit.levels.length === 1} className="ml-1 text-red-500 disabled:opacity-30" aria-label={`Xóa cấp ${i + 1}`}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <button onClick={() => setEdit({ ...edit, levels: [...edit.levels, blank()] })} className="rounded-full border border-slate-300 px-3 py-1" data-testid="signal-add-level">+ Thêm cấp độ</button>
            <span>Biến dùng trong lời ghép:</span>{meta.placeholders.map((p) => <code key={p} className="rounded bg-slate-500/15 px-1.5 py-0.5">{`{${p}}`}</code>)}
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setEdit(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
            <button onClick={save} disabled={!edit.name.trim() || (!edit.id && !edit.code.trim())} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="signal-save">Lưu</button>
          </div>
        </Modal>
      )}
    </div>
  );
}
