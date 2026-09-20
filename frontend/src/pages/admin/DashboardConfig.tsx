import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, NavLink, useParams } from "react-router-dom";
import { api, DashGroup, DashIndicator, DashOptions, DashRule, errorMessage, RuntimeItem } from "../../api/client";
import { DashActions, renderIndicator } from "../../components/dashboard/renderers";
import { useAuth } from "../../context/AuthContext";
import { dateTimeVi } from "../../lib/format";
import LayoutBuilder from "./LayoutBuilder";

const SECTIONS = [
  { key: "groups", label: "Nhóm chỉ số" },
  { key: "indicators", label: "Chỉ số theo dõi" },
  { key: "rules", label: "Rule Registry" },
  { key: "layouts", label: "Bố cục Dashboard" },
];

const NOOP: DashActions = { month: "", drillRevenue: () => undefined, drillOrder: () => undefined, drillQa: () => undefined, drillPo: () => undefined, drillHr: () => undefined, drillSignal: () => undefined };
const inputCls = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm";

function Toggle({ on, onChange, disabled, label }: { on: boolean; onChange: (v: boolean) => void; disabled?: boolean; label: string }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={`relative h-5 w-9 shrink-0 rounded-full transition ${on ? "bg-emerald-500" : "bg-slate-500/40"} ${disabled ? "opacity-50" : ""}`}
    >
      <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition ${on ? "left-[18px]" : "left-0.5"}`} />
    </button>
  );
}

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" onClick={onClose}>
      <div className={`max-h-[90vh] w-full overflow-y-auto rounded-2xl bg-white p-6 shadow-xl ${wide ? "max-w-3xl" : "max-w-xl"}`} onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-start justify-between">
          <h3 className="text-lg font-bold text-slate-900">{title}</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Đóng">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Nhóm chỉ số
function GroupsTab({ canManage }: { canManage: boolean }) {
  const [rows, setRows] = useState<DashGroup[]>([]);
  const [opts, setOpts] = useState<DashOptions | null>(null);
  const [edit, setEdit] = useState<Partial<DashGroup> | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    const [g, o] = await Promise.all([api.get<DashGroup[]>("/admin/dashboard/groups"), api.get<DashOptions>("/admin/dashboard/options")]);
    setRows(g.data);
    setOpts(o.data);
  }, []);
  useEffect(() => {
    load().catch((e) => setErr(errorMessage(e)));
  }, [load]);

  const patch = async (code: string, body: Partial<DashGroup>) => {
    try {
      await api.put(`/admin/dashboard/groups/${code}`, body);
      await load();
    } catch (e) {
      setErr(errorMessage(e));
    }
  };
  const move = async (i: number, dir: -1 | 1) => {
    const a = rows[i], b = rows[i + dir];
    if (!a || !b) return;
    await patch(a.group_code, { display_order: b.display_order });
    await patch(b.group_code, { display_order: a.display_order });
  };
  const save = async () => {
    if (!edit) return;
    try {
      if (edit.id) await api.put(`/admin/dashboard/groups/${edit.group_code}`, edit);
      else await api.post("/admin/dashboard/groups", { ...edit, display_order: edit.display_order ?? rows.length + 1 });
      setEdit(null);
      await load();
    } catch (e) {
      setErr(errorMessage(e));
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">Nhóm gom các chỉ số cùng chủ đề. Tắt nhóm sẽ ẩn mọi chỉ số của nhóm trên Dashboard (không xóa dữ liệu).</p>
        {canManage && <button onClick={() => setEdit({ group_code: "", group_name: "", layout_mode: "GRID", default_enabled: true, is_active: true, collapsible: false })} className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white">+ Thêm nhóm</button>}
      </div>
      {err && <p className="text-sm text-red-600">{err}</p>}
      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
              <th className="px-4 py-2.5">Bật</th><th>Mã nhóm</th><th>Tên nhóm</th><th>Mô tả</th><th>Layout mode</th><th>Collapsible</th><th>Thứ tự</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((g, i) => (
              <tr key={g.id} className="border-b border-slate-50" data-testid={`group-${g.group_code}`}>
                <td className="px-4 py-2"><Toggle on={g.is_active} disabled={!canManage} label={`Bật nhóm ${g.group_code}`} onChange={(v) => patch(g.group_code, { is_active: v })} /></td>
                <td className="font-mono text-xs">{g.group_code}</td>
                <td className="font-medium text-slate-800">{g.group_name}</td>
                <td className="max-w-[260px] truncate text-slate-500">{g.description}</td>
                <td>{g.layout_mode}</td>
                <td>{g.collapsible ? "Có" : "—"}</td>
                <td className="whitespace-nowrap">
                  {g.display_order}
                  {canManage && (
                    <>
                      <button aria-label="Lên" disabled={i === 0} onClick={() => move(i, -1)} className="ml-2 px-1 disabled:opacity-30">▲</button>
                      <button aria-label="Xuống" disabled={i === rows.length - 1} onClick={() => move(i, 1)} className="px-1 disabled:opacity-30">▼</button>
                    </>
                  )}
                </td>
                <td className="pr-4 text-right">{canManage && <button onClick={() => setEdit(g)} className="text-brand hover:underline">Sửa</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {edit && (
        <Modal title={edit.id ? `Sửa nhóm ${edit.group_code}` : "Thêm nhóm"} onClose={() => setEdit(null)}>
          <div className="space-y-3">
            {!edit.id && <label className="block text-xs text-slate-500">Mã nhóm<input className={inputCls} value={edit.group_code ?? ""} onChange={(e) => setEdit({ ...edit, group_code: e.target.value.toUpperCase() })} /></label>}
            <label className="block text-xs text-slate-500">Tên nhóm<input className={inputCls} value={edit.group_name ?? ""} onChange={(e) => setEdit({ ...edit, group_name: e.target.value })} /></label>
            <label className="block text-xs text-slate-500">Mô tả<input className={inputCls} value={edit.description ?? ""} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></label>
            <label className="block text-xs text-slate-500">Layout mode
              <select className={inputCls} value={edit.layout_mode} onChange={(e) => setEdit({ ...edit, layout_mode: e.target.value })}>{opts?.layout_modes.map((m) => <option key={m}>{m}</option>)}</select>
            </label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!edit.collapsible} onChange={(e) => setEdit({ ...edit, collapsible: e.target.checked })} /> Cho phép thu gọn</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={!!edit.default_enabled} onChange={(e) => setEdit({ ...edit, default_enabled: e.target.checked })} /> Bật mặc định khi tạo bố cục mới</label>
          </div>
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setEdit(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
            <button onClick={save} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white">Lưu</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Chỉ số
function IndicatorEditor({ initial, groups, rules, opts, onClose, onSaved }: { initial: Partial<DashIndicator>; groups: DashGroup[]; rules: DashRule[]; opts: DashOptions; onClose: () => void; onSaved: () => void }) {
  const [d, setD] = useState<Partial<DashIndicator>>(initial);
  const [cfg, setCfg] = useState(JSON.stringify(initial.config_json ?? {}, null, 2));
  const [err, setErr] = useState("");
  const isNew = !initial.id;

  const save = async () => {
    let config_json: Record<string, unknown>;
    try {
      config_json = JSON.parse(cfg || "{}");
    } catch {
      setErr("Advanced Config phải là JSON hợp lệ");
      return;
    }
    try {
      const body = { ...d, config_json, data_freshness_requirement: d.data_freshness_requirement ?? "" };
      if (isNew) await api.post("/admin/dashboard/indicators", body);
      else await api.put(`/admin/dashboard/indicators/${d.indicator_code}`, body);
      onSaved();
    } catch (e) {
      setErr(errorMessage(e));
    }
  };
  const F = ({ label, children }: { label: string; children: React.ReactNode }) => <label className="block text-xs text-slate-500">{label}{children}</label>;
  const H = ({ t }: { t: string }) => <h4 className="mt-4 border-b border-slate-100 pb-1 text-xs font-bold uppercase text-slate-400">{t}</h4>;

  return (
    <Modal title={isNew ? "Thêm chỉ số" : `Sửa chỉ số ${d.indicator_code}`} onClose={onClose} wide>
      <H t="General" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {isNew && <F label="Mã chỉ số"><input className={inputCls} value={d.indicator_code ?? ""} onChange={(e) => setD({ ...d, indicator_code: e.target.value.toUpperCase() })} /></F>}
        <F label="Tên chỉ số"><input className={inputCls} value={d.indicator_name ?? ""} onChange={(e) => setD({ ...d, indicator_name: e.target.value })} /></F>
        <F label="Nhóm"><select className={inputCls} value={d.group_code ?? ""} onChange={(e) => setD({ ...d, group_code: e.target.value })}><option value="">—</option>{groups.map((g) => <option key={g.group_code} value={g.group_code}>{g.group_name}</option>)}</select></F>
        <F label="Phụ trách (owner)"><input className={inputCls} value={d.owner ?? ""} onChange={(e) => setD({ ...d, owner: e.target.value })} /></F>
      </div>
      <F label="Mô tả"><input className={inputCls} value={d.description ?? ""} onChange={(e) => setD({ ...d, description: e.target.value })} /></F>
      <H t="Display" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <F label="Loại hiển thị"><select className={inputCls} value={d.display_type} onChange={(e) => setD({ ...d, display_type: e.target.value })}>{opts.display_types.map((t) => <option key={t}>{t}</option>)}</select></F>
        <F label="Phạm vi (scope)"><select className={inputCls} value={d.default_scope} onChange={(e) => setD({ ...d, default_scope: e.target.value as DashIndicator["default_scope"] })}>{opts.scopes.map((t) => <option key={t}>{t}</option>)}</select></F>
      </div>
      <H t="Rule" />
      <F label="Rule (chỉ chọn rule đã đăng ký trong code)">
        <select className={inputCls} value={d.rule_code ?? ""} onChange={(e) => setD({ ...d, rule_code: e.target.value })}>
          <option value="">—</option>
          {rules.map((r) => <option key={r.rule_code} value={r.rule_code} disabled={!r.is_active}>{r.rule_code} — {r.rule_name}{r.is_active ? "" : " (đã tắt)"}</option>)}
        </select>
      </F>
      <H t="Data" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <F label="Nguồn dữ liệu"><input className={inputCls} value={d.data_source ?? ""} onChange={(e) => setD({ ...d, data_source: e.target.value })} /></F>
        <F label="Chế độ làm mới"><select className={inputCls} value={d.refresh_mode} onChange={(e) => setD({ ...d, refresh_mode: e.target.value })}>{opts.refresh_modes.map((t) => <option key={t}>{t}</option>)}</select></F>
        <F label="Độ tươi tối đa (giờ)"><input className={inputCls} value={d.data_freshness_requirement ?? ""} placeholder="VD 48" onChange={(e) => setD({ ...d, data_freshness_requirement: e.target.value })} /></F>
      </div>
      <H t="Drilldown" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <F label="Loại drilldown"><select className={inputCls} value={d.drilldown_type} onChange={(e) => setD({ ...d, drilldown_type: e.target.value })}>{opts.drilldowns.map((t) => <option key={t}>{t}</option>)}</select></F>
        <F label="Đích drilldown"><input className={inputCls} value={d.drilldown_target ?? ""} onChange={(e) => setD({ ...d, drilldown_target: e.target.value })} /></F>
      </div>
      <H t="Advanced Config (JSON)" />
      <textarea className={`${inputCls} font-mono text-xs`} rows={5} spellCheck={false} value={cfg} onChange={(e) => setCfg(e.target.value)} aria-label="Advanced Config" />
      <div className="mt-3 flex flex-wrap gap-5 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" checked={!!d.is_active} onChange={(e) => setD({ ...d, is_active: e.target.checked })} /> Đang hoạt động (is_active)</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={!!d.default_enabled} onChange={(e) => setD({ ...d, default_enabled: e.target.checked })} /> Bật mặc định khi tạo bố cục mới</label>
      </div>
      {err && <p className="mt-3 text-sm text-red-600" role="alert">{err}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
        <button onClick={save} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white">Lưu</button>
      </div>
    </Modal>
  );
}

function IndicatorsTab({ canManage, canTest }: { canManage: boolean; canTest: boolean }) {
  const [rows, setRows] = useState<DashIndicator[]>([]);
  const [groups, setGroups] = useState<DashGroup[]>([]);
  const [rules, setRules] = useState<DashRule[]>([]);
  const [opts, setOpts] = useState<DashOptions | null>(null);
  const [edit, setEdit] = useState<Partial<DashIndicator> | null>(null);
  const [preview, setPreview] = useState<{ item: RuntimeItem; scope: string } | null>(null);
  const [msg, setMsg] = useState("");
  const [q, setQ] = useState("");

  const load = useCallback(async () => {
    const [i, g, r, o] = await Promise.all([
      api.get<DashIndicator[]>("/admin/dashboard/indicators"), api.get<DashGroup[]>("/admin/dashboard/groups"),
      api.get<DashRule[]>("/admin/dashboard/rules"), api.get<DashOptions>("/admin/dashboard/options"),
    ]);
    setRows(i.data); setGroups(g.data); setRules(r.data); setOpts(o.data);
  }, []);
  useEffect(() => {
    load().catch((e) => setMsg(errorMessage(e)));
  }, [load]);

  const gname = (code: string) => groups.find((g) => g.group_code === code)?.group_name ?? code;
  const toggle = async (i: DashIndicator, v: boolean) => {
    try {
      await api.put(`/admin/dashboard/indicators/${i.indicator_code}`, { is_active: v });
      await load();
    } catch (e) {
      setMsg(errorMessage(e));
    }
  };
  const doPreview = async (code: string, scope: string) => {
    try {
      const r = await api.post<{ indicator: DashIndicator; data: RuntimeItem["data"] }>(`/admin/dashboard/indicators/${code}/preview`, { scope });
      setPreview({ scope, item: { indicator: r.data.indicator, data: r.data.data, position: { section: "MAIN", x: 0, y: 0, w: 12, h: 3, order: 0, collapsed: false } } });
    } catch (e) {
      setMsg(errorMessage(e));
    }
  };
  const doTest = async (code: string) => {
    try {
      const r = await api.post<{ status: string; message: string; meta: { duration_ms?: number } }>(`/admin/dashboard/indicators/${code}/test`, { scope: "TONG" });
      setMsg(`Test ${code}: ${r.data.status}${r.data.message ? " — " + r.data.message : ""} (${r.data.meta.duration_ms ?? 0} ms)`);
    } catch (e) {
      setMsg(errorMessage(e));
    }
  };
  const duplicate = async (code: string) => {
    const nc = window.prompt("Mã chỉ số mới cho bản sao:", `${code}_COPY`);
    if (!nc) return;
    try {
      await api.post(`/admin/dashboard/indicators/${code}/duplicate`, { new_code: nc });
      await load();
    } catch (e) {
      setMsg(errorMessage(e));
    }
  };
  const shown = rows.filter((r) => !q || `${r.indicator_code} ${r.indicator_name}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm chỉ số..." className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm" aria-label="Tìm chỉ số" />
        {canManage && opts && (
          <button
            onClick={() => setEdit({ indicator_code: "", indicator_name: "", group_code: groups[0]?.group_code ?? "", display_type: "KPI_CARD", rule_code: "", default_scope: "BOTH", drilldown_type: "NONE", refresh_mode: "ON_LOAD", default_enabled: true, is_active: true, config_json: {} })}
            className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white"
          >
            + Thêm chỉ số
          </button>
        )}
      </div>
      {msg && <p className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600" role="status">{msg}</p>}
      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
              <th className="px-4 py-2.5">Bật</th><th>Nhóm</th><th>Mã</th><th>Tên</th><th>Loại hiển thị</th><th>Rule</th><th>Scope</th><th>Drilldown</th><th>Source</th><th />
            </tr>
          </thead>
          <tbody>
            {shown.map((i) => (
              <tr key={i.id} className="border-b border-slate-50" data-testid={`ind-${i.indicator_code}`}>
                <td className="px-4 py-2"><Toggle on={i.is_active} disabled={!canManage} label={`Bật chỉ số ${i.indicator_code}`} onChange={(v) => toggle(i, v)} /></td>
                <td>{gname(i.group_code)}</td>
                <td className="font-mono text-xs">{i.indicator_code}</td>
                <td className="font-medium text-slate-800">{i.indicator_name}</td>
                <td><span className="pg-chip pg-known">{i.display_type}</span></td>
                <td className="font-mono text-xs">{i.rule_code}</td>
                <td>{i.default_scope}</td>
                <td>{i.drilldown_type}{i.drilldown_target ? ` · ${i.drilldown_target}` : ""}</td>
                <td className="text-slate-500">{i.data_source}</td>
                <td className="whitespace-nowrap pr-4 text-right text-xs">
                  <button onClick={() => doPreview(i.indicator_code, "TONG")} className="mr-2 text-brand hover:underline">Preview</button>
                  {canTest && <button onClick={() => doTest(i.indicator_code)} className="mr-2 text-brand hover:underline">Test Rule</button>}
                  {canManage && <button onClick={() => duplicate(i.indicator_code)} className="mr-2 text-brand hover:underline">Duplicate</button>}
                  {canManage && <button onClick={() => setEdit(i)} className="text-brand hover:underline">Sửa</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {edit && opts && <IndicatorEditor initial={edit} groups={groups} rules={rules} opts={opts} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} />}
      {preview && (
        <Modal title={`Preview — ${preview.item.indicator.indicator_name}`} onClose={() => setPreview(null)} wide>
          <div className="mb-3 flex gap-2 text-xs">
            {["TONG", "XN1", "XN2", "XN3"].map((s) => (
              <button key={s} onClick={() => doPreview(preview.item.indicator.indicator_code, s)} className={`rounded-full px-3 py-1 ${preview.scope === s ? "bg-brand text-white" : "border border-slate-300"}`}>{s === "TONG" ? "Tổng công ty" : s}</button>
            ))}
          </div>
          {renderIndicator(preview.item, NOOP)}
          <p className="mt-3 text-[11px] text-slate-400">Trạng thái rule: {preview.item.data.status} · v{preview.item.data.meta.rule_version} · {preview.item.data.meta.duration_ms ?? 0} ms · độ tươi {preview.item.data.meta.data_freshness}</p>
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Rule Registry
function RulesTab({ canManage, canTest }: { canManage: boolean; canTest: boolean }) {
  const [rows, setRows] = useState<DashRule[]>([]);
  const [open, setOpen] = useState<DashRule | null>(null);
  const [msg, setMsg] = useState("");
  const load = useCallback(async () => setRows((await api.get<DashRule[]>("/admin/dashboard/rules")).data), []);
  useEffect(() => {
    load().catch((e) => setMsg(errorMessage(e)));
  }, [load]);

  const test = async (code: string) => {
    try {
      const r = await api.post<{ status: string; message: string; meta: { duration_ms?: number } }>(`/admin/dashboard/rules/${code}/test`, { scope: "TONG" });
      setMsg(`Test ${code}: ${r.data.status}${r.data.message ? " — " + r.data.message : ""} (${r.data.meta.duration_ms ?? 0} ms)`);
      await load();
    } catch (e) {
      setMsg(errorMessage(e));
    }
  };
  const toggle = async (r: DashRule, v: boolean) => {
    try {
      await api.put(`/admin/dashboard/rules/${r.rule_code}`, { is_active: v });
      await load();
    } catch (e) {
      setMsg(errorMessage(e));
    }
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">Rule là hàm Python đã được đăng ký sẵn trong code (whitelist). Trang này chỉ xem, thử và bật/tắt — không nhập đường dẫn và không tải mã lên.</p>
      {msg && <p className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600" role="status">{msg}</p>}
      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
              <th className="px-4 py-2.5">Bật</th><th>Rule code</th><th>Tên</th><th>Module</th><th>Function</th><th>Version</th><th>Last test</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-slate-50" data-testid={`rule-${r.rule_code}`}>
                <td className="px-4 py-2"><Toggle on={r.is_active} disabled={!canManage} label={`Bật rule ${r.rule_code}`} onChange={(v) => toggle(r, v)} /></td>
                <td className="font-mono text-xs">{r.rule_code}{!r.registered && <span className="ml-1 text-red-500" title="Không còn trong code">⚠</span>}</td>
                <td className="font-medium text-slate-800">{r.rule_name}</td>
                <td className="font-mono text-xs text-slate-500">{r.rule_module}</td>
                <td className="font-mono text-xs text-slate-500">{r.rule_function}</td>
                <td>{r.rule_version}</td>
                <td className="text-xs text-slate-500">{r.last_test?.at ? `${r.last_test.status} · ${dateTimeVi(r.last_test.at)}` : "chưa test"}</td>
                <td className="whitespace-nowrap pr-4 text-right text-xs">
                  <button onClick={() => setOpen(r)} className="mr-2 text-brand hover:underline">View Contract</button>
                  {canTest && <button onClick={() => test(r.rule_code)} className="text-brand hover:underline">Test Rule</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && (
        <Modal title={`Contract — ${open.rule_code}`} onClose={() => setOpen(null)}>
          <p className="text-sm text-slate-700">{open.description}</p>
          <h4 className="mt-4 text-xs font-bold uppercase text-slate-400">Input contract</h4>
          <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-slate-500/10 p-3 text-xs">{open.input_contract}</pre>
          <h4 className="mt-4 text-xs font-bold uppercase text-slate-400">Output contract</h4>
          <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-slate-500/10 p-3 text-xs">{open.output_contract}</pre>
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Container
export default function DashboardConfig() {
  const { section } = useParams();
  const { can } = useAuth();
  const current = useMemo(() => SECTIONS.find((s) => s.key === section), [section]);
  if (!current) return <Navigate to="/admin/dashboard/indicators" replace />;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Cấu hình Dashboard</h1>
        <p className="text-xs text-slate-500">Mọi thành phần trên Dashboard đến từ metadata: nhóm → chỉ số → rule đã đăng ký → bố cục (Draft / Publish).</p>
      </div>
      <nav className="flex gap-1 border-b border-slate-200">
        {SECTIONS.map((s) => (
          <NavLink key={s.key} to={`/admin/dashboard/${s.key}`} className={({ isActive }) => `-mb-px border-b-2 px-4 py-2 text-sm font-medium ${isActive ? "border-brand text-brand" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
            {s.label}
          </NavLink>
        ))}
      </nav>
      {current.key === "groups" && <GroupsTab canManage={can("dashboard.config_manage")} />}
      {current.key === "indicators" && <IndicatorsTab canManage={can("dashboard.config_manage")} canTest={can("dashboard.rule_test")} />}
      {current.key === "rules" && <RulesTab canManage={can("dashboard.config_manage")} canTest={can("dashboard.rule_test")} />}
      {current.key === "layouts" && <LayoutBuilder canEdit={can("dashboard.layout_manage")} canPublish={can("dashboard.publish")} />}
    </div>
  );
}
