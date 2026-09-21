import { useCallback, useEffect, useMemo, useState } from "react";
import { api, DashIndicator, DashLayout, DashOptions, errorMessage, RuntimeResponse } from "../../api/client";
import DashboardCanvas from "../../components/dashboard/DashboardCanvas";
import { DashActions } from "../../components/dashboard/renderers";
import { dateTimeVi } from "../../lib/format";

const NOOP: DashActions = { month: "", drillRevenue: () => undefined, drillOrder: () => undefined, drillQa: () => undefined, drillPo: () => undefined, drillHr: () => undefined, drillSignal: () => undefined };
const STATUS_CHIP: Record<string, string> = { PUBLISHED: "pg-ok", DRAFT: "pg-adv", RETIRED: "pg-unk", SUPERSEDED: "pg-unk" };
const PRESET_LABEL: Record<string, string> = { "100": "100%", "50_50": "50 / 50", "66_34": "66 / 34", "34_66": "34 / 66", "33_33_33": "33 / 33 / 33", "25_25_25_25": "25 / 25 / 25 / 25" };
const DEFAULT_PRESETS: Record<string, number[]> = { "100": [12], "50_50": [6, 6], "66_34": [8, 4], "34_66": [4, 8], "33_33_33": [4, 4, 4], "25_25_25_25": [3, 3, 3, 3] };
const btn = "rounded-full border border-slate-300 px-3 py-1.5 text-xs";
const inp = "w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm";

interface DSec { ref: string; title: string; preset: string; is_visible: boolean }
interface DItem { uid: string; indicator_code: string; section_ref: string; column_no: number; is_visible: boolean; collapsed: boolean; config_override_json: Record<string, unknown> }
type Sel = { kind: "widget"; id: string } | { kind: "section"; id: string } | null;

let seq = 0;
const nid = (p: string) => `${p}${Date.now().toString(36)}${(seq++).toString(36)}`;

interface Props {
  canEdit: boolean;
  canPublish: boolean;
}

/** Dashboard Layout Designer (spec §8): View Mode mặc định; Edit Mode cho thêm Section (preset cột), thêm/kéo thả/nhân bản/ẩn widget, Save Draft, Preview, Publish. */
export default function LayoutDesigner({ canEdit, canPublish }: Props) {
  const [layouts, setLayouts] = useState<DashLayout[]>([]);
  const [indicators, setIndicators] = useState<DashIndicator[]>([]);
  const [factories, setFactories] = useState<string[]>([]);
  const [opts, setOpts] = useState<DashOptions | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [layout, setLayout] = useState<DashLayout | null>(null);
  const [edit, setEdit] = useState(false);
  const [sections, setSections] = useState<DSec[]>([]);
  const [items, setItems] = useState<DItem[]>([]);
  const [dirty, setDirty] = useState(false);
  const [sel, setSel] = useState<Sel>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [creating, setCreating] = useState(false);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const [viewScope, setViewScope] = useState("TONG");
  const [runtime, setRuntime] = useState<{ data: RuntimeResponse | null; error: string } | null>(null);
  const [preview, setPreview] = useState<{ scope: string; data: RuntimeResponse | null; error: string } | null>(null);

  const presets = opts?.section_presets ?? DEFAULT_PRESETS;
  const spansOf = (preset: string) => presets[preset] ?? [12];
  const nameOf = useMemo(() => new Map(indicators.map((i) => [i.indicator_code, i])), [indicators]);
  const ok = (text: string) => setMsg({ ok: true, text });
  const fail = (e: unknown) => setMsg({ ok: false, text: errorMessage(e) });

  const loadLists = useCallback(async () => {
    const [l, i, o, m] = await Promise.all([
      api.get<DashLayout[]>("/admin/dashboard/layouts"), api.get<DashIndicator[]>("/admin/dashboard/indicators"),
      api.get<DashOptions>("/admin/dashboard/options"), api.get<{ factories: { code: string }[] }>("/dashboard/meta"),
    ]);
    setLayouts(l.data); setIndicators(i.data); setOpts(o.data); setFactories(m.data.factories.map((f) => f.code));
    return l.data;
  }, []);

  const load = useCallback(async (id: number, intoEdit = false) => {
    const r = (await api.get<DashLayout>(`/admin/dashboard/layouts/${id}`)).data;
    setSelected(id);
    setLayout(r);
    setSections((r.sections ?? []).map((s) => ({ ref: String(s.id), title: s.title, preset: s.preset, is_visible: s.is_visible })));
    setItems((r.items ?? []).map((it) => ({ uid: `i${it.id}`, indicator_code: it.indicator_code, section_ref: String(it.section_id), column_no: it.column_no ?? 0, is_visible: it.is_visible, collapsed: it.collapsed, config_override_json: it.config_override_json ?? {} })));
    setDirty(false);
    setSel(null);
    setEdit(intoEdit && r.status === "DRAFT");
  }, []);

  useEffect(() => {
    loadLists()
      .then((l) => {
        const first = l.find((x) => x.status === "PUBLISHED" && x.scope_type === "COMPANY") ?? l[0];
        if (first) return load(first.id);
      })
      .catch(fail);
  }, [loadLists, load]);

  // View Mode: dựng thật bằng runtime của bố cục đang chọn
  useEffect(() => {
    if (!layout || edit) return;
    setRuntime({ data: null, error: "" });
    api.get<RuntimeResponse>("/dashboard/runtime", { params: { scope: viewScope, layout_id: layout.id } })
      .then((r) => setRuntime({ data: r.data, error: "" }))
      .catch((e) => setRuntime({ data: null, error: errorMessage(e) }));
  }, [layout, edit, viewScope]);

  const editable = edit && canEdit && layout?.status === "DRAFT";
  const touch = () => setDirty(true);

  // ------------------------------------------------------------------ thao tác Section
  const addSection = (preset = "100") => { const ref = nid("s"); setSections((c) => [...c, { ref, title: "", preset, is_visible: true }]); setSel({ kind: "section", id: ref }); touch(); return ref; };
  const patchSection = (ref: string, p: Partial<DSec>) => {
    setSections((c) => c.map((s) => (s.ref === ref ? { ...s, ...p } : s)));
    if (p.preset) { const n = spansOf(p.preset).length; setItems((c) => c.map((i) => (i.section_ref === ref ? { ...i, column_no: Math.min(i.column_no, n - 1) } : i))); }
    touch();
  };
  const moveSection = (ref: string, dir: -1 | 1) => {
    setSections((c) => { const i = c.findIndex((s) => s.ref === ref); const j = i + dir; if (i < 0 || j < 0 || j >= c.length) return c; const n = [...c]; [n[i], n[j]] = [n[j], n[i]]; return n; });
    touch();
  };
  const dupSection = (ref: string) => {
    const src = sections.find((s) => s.ref === ref);
    if (!src) return;
    const copy = nid("s");
    setSections((c) => { const i = c.findIndex((s) => s.ref === ref); const n = [...c]; n.splice(i + 1, 0, { ...src, ref: copy, title: src.title ? `${src.title} (bản sao)` : "" }); return n; });
    setItems((c) => [...c, ...c.filter((i) => i.section_ref === ref).map((i) => ({ ...i, uid: nid("i"), section_ref: copy }))]);
    touch();
  };
  const removeSection = (ref: string) => {
    if (items.some((i) => i.section_ref === ref) && !window.confirm("Section này có widget — xóa Section sẽ gỡ luôn các widget trong đó?")) return;
    setSections((c) => c.filter((s) => s.ref !== ref));
    setItems((c) => c.filter((i) => i.section_ref !== ref));
    setSel(null);
    touch();
  };

  // ------------------------------------------------------------------ thao tác Widget
  const insert = (list: DItem[], it: DItem, before?: string): DItem[] => {
    if (!before) return [...list, it];
    const i = list.findIndex((x) => x.uid === before);
    if (i < 0) return [...list, it];
    const n = [...list]; n.splice(i, 0, it); return n;
  };
  const addWidget = (code: string, ref?: string, col = 0, before?: string) => {
    let target = ref ?? (sel?.kind === "section" ? sel.id : sel?.kind === "widget" ? items.find((i) => i.uid === sel.id)?.section_ref : undefined) ?? sections[sections.length - 1]?.ref;
    if (!target) target = addSection("100");
    const it: DItem = { uid: nid("i"), indicator_code: code, section_ref: target, column_no: col, is_visible: true, collapsed: false, config_override_json: {} };
    setItems((c) => insert(c, it, before));
    setSel({ kind: "widget", id: it.uid });
    touch();
  };
  const moveWidget = (uid: string, ref: string, col: number, before?: string) => {
    if (uid === before) return;
    setItems((c) => { const it = c.find((i) => i.uid === uid); if (!it) return c; return insert(c.filter((i) => i.uid !== uid), { ...it, section_ref: ref, column_no: col }, before); });
    touch();
  };
  const stepWidget = (uid: string, dir: -1 | 1) => {
    setItems((c) => {
      const it = c.find((i) => i.uid === uid);
      if (!it) return c;
      const mates = c.filter((i) => i.section_ref === it.section_ref && i.column_no === it.column_no);
      const k = mates.findIndex((i) => i.uid === uid);
      const other = mates[k + dir];
      if (!other) return c;
      const n = [...c]; const a = n.findIndex((i) => i.uid === uid); const b = n.findIndex((i) => i.uid === other.uid); [n[a], n[b]] = [n[b], n[a]]; return n;
    });
    touch();
  };
  const dupWidget = (uid: string) => {
    const src = items.find((i) => i.uid === uid);
    if (!src) return;
    const cp = { ...src, uid: nid("i"), config_override_json: { ...src.config_override_json } };
    const i = items.findIndex((x) => x.uid === uid);
    setItems((c) => { const n = [...c]; n.splice(i + 1, 0, cp); return n; });
    setSel({ kind: "widget", id: cp.uid });
    touch();
  };
  const patchWidget = (uid: string, p: Partial<DItem>) => { setItems((c) => c.map((i) => (i.uid === uid ? { ...i, ...p } : i))); touch(); };
  const removeWidget = (uid: string) => { setItems((c) => c.filter((i) => i.uid !== uid)); setSel(null); touch(); };

  const onDrop = (e: React.DragEvent, ref: string, col: number, before?: string) => {
    if (!editable) return;
    e.preventDefault();
    e.stopPropagation();
    const data = e.dataTransfer.getData("text/plain");
    if (data.startsWith("w:")) moveWidget(data.slice(2), ref, col, before);
    else if (data.startsWith("c:")) addWidget(data.slice(2), ref, col, before);
  };

  // ------------------------------------------------------------------ lưu / publish / preview
  const payload = () => ({
    layout_name: layout?.layout_name,
    sections: sections.map((s) => ({ ref: s.ref, title: s.title, preset: s.preset, is_visible: s.is_visible })),
    items: items.map((i) => ({ indicator_code: i.indicator_code, section_ref: i.section_ref, column_no: i.column_no, is_visible: i.is_visible, collapsed: i.collapsed, config_override_json: i.config_override_json })),
  });
  const save = async (): Promise<boolean> => {
    if (!layout) return false;
    try {
      await api.put(`/admin/dashboard/layouts/${layout.id}`, payload());
      await load(layout.id, true);
      ok("Đã lưu bản nháp.");
      return true;
    } catch (e) { fail(e); return false; }
  };
  const enterEdit = async () => {
    if (!layout) return;
    if (layout.status === "DRAFT") return setEdit(true);
    try {
      const r = await api.post<DashLayout>(`/admin/dashboard/layouts/${layout.id}/clone`);
      await loadLists();
      await load(r.data.id, true);
      ok(`Đã tạo bản nháp v${r.data.version} từ bản ${layout.status}. Chỉnh sửa rồi Publish.`);
    } catch (e) {
      const draft = layouts.find((l) => l.layout_code === layout.layout_code && l.status === "DRAFT");
      if (draft) { await load(draft.id, true); ok(`Đang mở bản nháp có sẵn v${draft.version}.`); } else fail(e);
    }
  };
  const cancel = async () => {
    if (dirty && !window.confirm("Bỏ các thay đổi chưa lưu?")) return;
    if (layout) await load(layout.id, false);
    setEdit(false);
  };
  const publish = async () => {
    if (!layout) return;
    setConfirmPublish(false);
    if (dirty && !(await save())) return;
    try {
      await api.post(`/admin/dashboard/layouts/${layout.id}/publish`);
      await loadLists();
      await load(layout.id, false);
      ok("Đã Publish — Dashboard dùng bố cục mới ngay; bản cũ được chuyển sang RETIRED.");
    } catch (e) { fail(e); }
  };
  const runPreview = async (scope: string) => {
    if (!layout) return;
    if (dirty && editable && !(await save())) return;
    setPreview({ scope, data: null, error: "" });
    try {
      setPreview({ scope, data: (await api.get<RuntimeResponse>("/dashboard/runtime", { params: { scope, layout_id: layout.id } })).data, error: "" });
    } catch (e) { setPreview({ scope, data: null, error: errorMessage(e) }); }
  };
  const createLayout = async (body: { layout_code: string; layout_name: string; scope_type: string; scope_value: string }) => {
    try {
      const r = await api.post<DashLayout>("/admin/dashboard/layouts", body);
      setCreating(false);
      await loadLists();
      await load(r.data.id, true);
      ok("Đã tạo bản nháp mới.");
    } catch (e) { fail(e); }
  };

  const selWidget = sel?.kind === "widget" ? items.find((i) => i.uid === sel.id) : undefined;
  const selSection = sel?.kind === "section" ? sections.find((s) => s.ref === sel.id) : undefined;
  const groups = useMemo(() => {
    const m = new Map<string, DashIndicator[]>();
    indicators.filter((i) => i.is_active).forEach((i) => m.set(i.group_name ?? i.group_code, [...(m.get(i.group_name ?? i.group_code) ?? []), i]));
    return [...m.entries()];
  }, [indicators]);

  return (
    <div className={`grid grid-cols-1 gap-4 ${editable ? "xl:grid-cols-[240px_1fr_260px]" : "xl:grid-cols-[240px_1fr]"}`} data-testid="layout-designer">
      <aside className="space-y-4">
        <section className="rounded-2xl border border-slate-200 bg-white p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase text-slate-400">Bố cục</h3>
            {canEdit && <button onClick={() => setCreating(true)} className="text-xs text-brand hover:underline">+ Bố cục mới</button>}
          </div>
          <ul className="max-h-56 space-y-1 overflow-y-auto">
            {layouts.map((l) => (
              <li key={l.id}>
                <button onClick={() => (dirty && !window.confirm("Bỏ thay đổi chưa lưu?") ? undefined : load(l.id))} className={`flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-xs ${selected === l.id ? "bg-brand/20" : "hover:bg-slate-500/10"}`} data-testid={`layout-${l.layout_code}-v${l.version}`}>
                  <span className="min-w-0 truncate"><b>{l.layout_code}</b> v{l.version}<span className="block text-[10px] text-slate-400">{l.scope_type}{l.scope_value ? `:${l.scope_value}` : ""}</span></span>
                  <span className={`pg-chip ${STATUS_CHIP[l.status]}`}>{l.status}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        {editable && (
          <section className="rounded-2xl border border-slate-200 bg-white p-3" data-testid="widget-catalog">
            <h3 className="mb-2 text-xs font-bold uppercase text-slate-400">Widget</h3>
            <p className="mb-2 text-[11px] text-slate-400">Kéo vào cột, hoặc bấm "+" để thêm vào Section đang chọn.</p>
            {groups.map(([g, list]) => (
              <div key={g} className="mb-2">
                <p className="text-[10px] font-bold uppercase text-slate-400">{g}</p>
                <ul className="space-y-1">
                  {list.map((i) => (
                    <li key={i.indicator_code} draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", `c:${i.indicator_code}`)} className="flex cursor-grab items-center justify-between rounded-lg border border-slate-200 px-2 py-1 text-xs" data-testid={`cat-${i.indicator_code}`}>
                      <span className="min-w-0 truncate">⠿ {i.indicator_name}</span>
                      <button onClick={() => addWidget(i.indicator_code)} className="ml-2 shrink-0 text-brand" aria-label={`Thêm ${i.indicator_name}`}>+</button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </section>
        )}
      </aside>

      <div className="min-w-0 space-y-3">
        {layout && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-base font-bold text-slate-900">
                {layout.layout_name} <span className="text-slate-400">· {layout.layout_code} v{layout.version}</span> <span className={`pg-chip ${STATUS_CHIP[layout.status]}`}>{layout.status}</span>
                <span className="ml-2 text-xs font-normal text-slate-400">{editable ? "Edit Mode" : "View Mode"}</span>
              </h2>
              <p className="text-xs text-slate-500">
                Phạm vi {layout.scope_type}{layout.scope_value ? ` (${layout.scope_value})` : ""}
                {layout.published_at ? ` · Publish ${dateTimeVi(layout.published_at)} bởi ${layout.published_by}` : ""}
                {layout.status !== "DRAFT" ? " · bất biến — bấm Edit Mode để tạo bản nháp" : ""}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {!editable && canEdit && <button onClick={enterEdit} className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white" data-testid="edit-mode">Edit Mode</button>}
              {editable && <button onClick={() => addSection("100")} className={btn} data-testid="add-section">+ Section</button>}
              {editable && <button onClick={() => runPreview("TONG")} className={btn}>Preview</button>}
              {editable && <button onClick={save} disabled={!dirty} className={`${btn} disabled:opacity-40`} data-testid="save-draft">Save Draft</button>}
              {editable && <button onClick={cancel} className={btn}>Cancel</button>}
              {editable && canPublish && <button onClick={() => setConfirmPublish(true)} disabled={items.filter((i) => i.is_visible).length === 0} className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-40" data-testid="publish">Publish</button>}
            </div>
          </div>
        )}
        {msg && <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}

        {!layout && <p className="text-sm text-slate-500">Chọn một bố cục ở bên trái.</p>}

        {layout && !editable && (
          <div className="space-y-3">
            <div className="flex gap-1 text-xs">
              {["TONG", ...factories].map((s) => <button key={s} onClick={() => setViewScope(s)} className={`rounded-full px-3 py-1 ${viewScope === s ? "bg-brand text-white" : "border border-slate-300"}`}>{s === "TONG" ? "Tổng công ty" : s}</button>)}
            </div>
            {runtime?.error && <p className="text-sm text-red-600">{runtime.error}</p>}
            {runtime && !runtime.data && !runtime.error && <p className="text-sm text-slate-500">Đang dựng...</p>}
            {runtime?.data && <DashboardCanvas runtime={runtime.data} actions={NOOP} />}
          </div>
        )}

        {editable && (
          <div className="space-y-3" data-testid="designer-canvas">
            {sections.length === 0 && <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-400">Bố cục trống — bấm "+ Section" rồi thêm widget.</p>}
            {sections.map((sec, si) => {
              const spans = spansOf(sec.preset);
              const isSel = sel?.kind === "section" && sel.id === sec.ref;
              return (
                <section key={sec.ref} className={`rounded-2xl border-2 p-3 ${isSel ? "border-brand" : "border-slate-200"} ${sec.is_visible ? "" : "opacity-50"} bg-white`} data-testid={`section-${si}`} data-preset={sec.preset}>
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                    <button onClick={() => setSel({ kind: "section", id: sec.ref })} className="font-semibold text-slate-700 hover:underline">{sec.title || `Section ${si + 1}`}</button>
                    <select value={sec.preset} onChange={(e) => patchSection(sec.ref, { preset: e.target.value })} className="rounded border border-slate-200 px-1 py-0.5" aria-label={`Preset Section ${si + 1}`} data-testid={`preset-${si}`}>
                      {Object.keys(presets).map((p) => <option key={p} value={p}>{PRESET_LABEL[p] ?? p}</option>)}
                    </select>
                    <span className="flex-1" />
                    <button onClick={() => moveSection(sec.ref, -1)} disabled={si === 0} title="Lên" className="disabled:opacity-30">↑</button>
                    <button onClick={() => moveSection(sec.ref, 1)} disabled={si === sections.length - 1} title="Xuống" className="disabled:opacity-30">↓</button>
                    <button onClick={() => dupSection(sec.ref)} title="Nhân bản Section">⧉</button>
                    <button onClick={() => patchSection(sec.ref, { is_visible: !sec.is_visible })} title={sec.is_visible ? "Ẩn Section" : "Hiện Section"}>{sec.is_visible ? "👁" : "🚫"}</button>
                    <button onClick={() => removeSection(sec.ref)} title="Xóa Section" aria-label={`Xóa Section ${si + 1}`}>✕</button>
                  </div>
                  <div className="grid gap-2" style={{ gridTemplateColumns: spans.map((s) => `${s}fr`).join(" ") }}>
                    {spans.map((_s, ci) => {
                      const cards = items.filter((i) => i.section_ref === sec.ref && Math.min(i.column_no, spans.length - 1) === ci);
                      return (
                        <div key={ci} onDragOver={(e) => e.preventDefault()} onDrop={(e) => onDrop(e, sec.ref, ci)} className="min-h-[72px] space-y-1.5 rounded-xl border border-dashed border-slate-300 p-1.5" data-testid={`col-${si}-${ci}`}>
                          {cards.map((it) => {
                            const ind = nameOf.get(it.indicator_code);
                            const isW = sel?.kind === "widget" && sel.id === it.uid;
                            return (
                              <div key={it.uid} draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", `w:${it.uid}`)} onDragOver={(e) => e.preventDefault()} onDrop={(e) => onDrop(e, sec.ref, ci, it.uid)} onClick={() => setSel({ kind: "widget", id: it.uid })}
                                className={`cursor-grab rounded-lg border px-2 py-1.5 text-xs ${isW ? "border-brand bg-indigo-500/20" : "border-indigo-400/40 bg-indigo-500/10"} ${it.is_visible ? "" : "opacity-50"}`} data-testid={`w-${it.indicator_code}`}>
                                <div className="flex items-center gap-1">
                                  <span className="min-w-0 flex-1 truncate font-semibold">⠿ {ind?.indicator_name ?? it.indicator_code}</span>
                                  <button onClick={(e) => { e.stopPropagation(); stepWidget(it.uid, -1); }} title="Lên" aria-label="Lên">↑</button>
                                  <button onClick={(e) => { e.stopPropagation(); stepWidget(it.uid, 1); }} title="Xuống" aria-label="Xuống">↓</button>
                                  <button onClick={(e) => { e.stopPropagation(); dupWidget(it.uid); }} title="Nhân bản" aria-label={`Nhân bản ${it.indicator_code}`}>⧉</button>
                                  <button onClick={(e) => { e.stopPropagation(); patchWidget(it.uid, { is_visible: !it.is_visible }); }} title={it.is_visible ? "Ẩn" : "Hiện"} aria-label={`${it.is_visible ? "Ẩn" : "Hiện"} ${it.indicator_code}`}>{it.is_visible ? "👁" : "🚫"}</button>
                                  <button onClick={(e) => { e.stopPropagation(); removeWidget(it.uid); }} title="Gỡ" aria-label={`Gỡ ${it.indicator_code}`}>✕</button>
                                </div>
                                <div className="text-[10px] text-slate-400">{ind?.display_type}{it.collapsed ? " · thu gọn" : ""}</div>
                              </div>
                            );
                          })}
                          {cards.length === 0 && <p className="py-3 text-center text-[11px] text-slate-400">Kéo widget vào đây</p>}
                        </div>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        )}
        <p className="text-[11px] text-slate-400">Bố cục theo Section và cột preset — không resize pixel tự do. Người dùng thường chỉ thấy bản Publish.</p>
      </div>

      {editable && (
        <aside className="space-y-3" data-testid="property-panel">
          <section className="rounded-2xl border border-slate-200 bg-white p-3">
            <h3 className="mb-2 text-xs font-bold uppercase text-slate-400">Thuộc tính</h3>
            {!selWidget && !selSection && <p className="text-xs text-slate-400">Chọn một Section hoặc widget để chỉnh thuộc tính.</p>}
            {selSection && (
              <div className="space-y-2 text-xs">
                <p className="font-semibold text-slate-700">Section</p>
                <label className="block text-slate-500">Tiêu đề (chỉ hiển thị trong Designer)<input className={inp} value={selSection.title} onChange={(e) => patchSection(selSection.ref, { title: e.target.value })} /></label>
                <label className="block text-slate-500">Số cột / tỉ lệ
                  <select className={inp} value={selSection.preset} onChange={(e) => patchSection(selSection.ref, { preset: e.target.value })}>{Object.keys(presets).map((p) => <option key={p} value={p}>{PRESET_LABEL[p] ?? p}</option>)}</select>
                </label>
                <label className="flex items-center gap-2 text-slate-600"><input type="checkbox" checked={selSection.is_visible} onChange={(e) => patchSection(selSection.ref, { is_visible: e.target.checked })} /> Hiển thị</label>
              </div>
            )}
            {selWidget && (
              <div className="space-y-2 text-xs">
                <p className="font-semibold text-slate-700">{nameOf.get(selWidget.indicator_code)?.indicator_name ?? selWidget.indicator_code}</p>
                <p className="text-slate-400">{nameOf.get(selWidget.indicator_code)?.display_type} · {selWidget.indicator_code}</p>
                <label className="flex items-center gap-2 text-slate-600"><input type="checkbox" checked={selWidget.is_visible} onChange={(e) => patchWidget(selWidget.uid, { is_visible: e.target.checked })} /> Hiển thị</label>
                <label className="flex items-center gap-2 text-slate-600"><input type="checkbox" checked={selWidget.collapsed} onChange={(e) => patchWidget(selWidget.uid, { collapsed: e.target.checked })} /> Thu gọn mặc định</label>
                <label className="block text-slate-500">Chuyển sang Section
                  <select className={inp} value={selWidget.section_ref} onChange={(e) => moveWidget(selWidget.uid, e.target.value, 0)}>{sections.map((s, i) => <option key={s.ref} value={s.ref}>{s.title || `Section ${i + 1}`}</option>)}</select>
                </label>
                <label className="block text-slate-500">Cột
                  <select className={inp} value={selWidget.column_no} onChange={(e) => patchWidget(selWidget.uid, { column_no: Number(e.target.value) })}>
                    {spansOf(sections.find((s) => s.ref === selWidget.section_ref)?.preset ?? "100").map((_s, i) => <option key={i} value={i}>Cột {i + 1}</option>)}
                  </select>
                </label>
                {nameOf.get(selWidget.indicator_code)?.display_type === "TEXT" && (
                  <>
                    <label className="block text-slate-500">Nội dung<textarea className={inp} rows={3} value={String(selWidget.config_override_json.text ?? "")} onChange={(e) => patchWidget(selWidget.uid, { config_override_json: { ...selWidget.config_override_json, text: e.target.value } })} data-testid="prop-text" /></label>
                    <label className="flex items-center gap-2 text-slate-600"><input type="checkbox" checked={Boolean(selWidget.config_override_json.heading ?? true)} onChange={(e) => patchWidget(selWidget.uid, { config_override_json: { ...selWidget.config_override_json, heading: e.target.checked } })} /> Hiển thị dạng tiêu đề</label>
                  </>
                )}
              </div>
            )}
          </section>
        </aside>
      )}

      {creating && <NewLayoutModal factories={factories} onClose={() => setCreating(false)} onCreate={createLayout} />}

      {confirmPublish && layout && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 text-slate-900 shadow-xl">
            <h3 className="text-lg font-bold">Publish bố cục?</h3>
            <p className="mt-2 text-sm text-slate-600">{layout.layout_code} v{layout.version} sẽ trở thành bố cục mặc định cho phạm vi {layout.scope_type}{layout.scope_value ? ` (${layout.scope_value})` : ""} và áp dụng ngay cho mọi người dùng. Bản Published trước đó chuyển sang RETIRED. Bản đã Publish là bất biến.</p>
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => setConfirmPublish(false)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
              <button onClick={publish} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white" data-testid="confirm-publish">Xác nhận Publish</button>
            </div>
          </div>
        </div>
      )}

      {preview && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4" role="dialog" aria-modal="true" onClick={() => setPreview(null)}>
          <div className="my-4 w-full max-w-6xl rounded-2xl bg-white p-5 text-slate-900 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-base font-bold">Preview — {layout?.layout_code} v{layout?.version}</h3>
              <div className="flex gap-2 text-xs">
                {["TONG", ...factories].map((s) => <button key={s} onClick={() => runPreview(s)} className={`rounded-full px-3 py-1 ${preview.scope === s ? "bg-brand text-white" : "border border-slate-300"}`}>{s === "TONG" ? "Tổng công ty" : s}</button>)}
                <button onClick={() => setPreview(null)} className="ml-2 text-slate-400 hover:text-slate-700" aria-label="Đóng">✕</button>
              </div>
            </div>
            {preview.error && <p className="text-sm text-red-600">{preview.error}</p>}
            {!preview.data && !preview.error && <p className="text-sm text-slate-500">Đang dựng...</p>}
            {preview.data && <DashboardCanvas runtime={preview.data} actions={NOOP} />}
          </div>
        </div>
      )}
    </div>
  );
}

function NewLayoutModal({ factories, onClose, onCreate }: { factories: string[]; onClose: () => void; onCreate: (b: { layout_code: string; layout_name: string; scope_type: string; scope_value: string }) => void }) {
  const [b, setB] = useState({ layout_code: "", layout_name: "", scope_type: "COMPANY", scope_value: "" });
  const cls = "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="w-full max-w-md rounded-2xl bg-white p-6 text-slate-900 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-4 text-lg font-bold">Bố cục mới (bản nháp)</h3>
        <div className="space-y-3">
          <label className="block text-xs text-slate-500">Mã bố cục<input className={cls} value={b.layout_code} onChange={(e) => setB({ ...b, layout_code: e.target.value.toUpperCase() })} placeholder="EXECUTIVE_2026" /></label>
          <label className="block text-xs text-slate-500">Tên<input className={cls} value={b.layout_name} onChange={(e) => setB({ ...b, layout_name: e.target.value })} /></label>
          <label className="block text-xs text-slate-500">Phạm vi
            <select className={cls} value={b.scope_type} onChange={(e) => setB({ ...b, scope_type: e.target.value, scope_value: "" })}><option value="COMPANY">Tổng công ty (COMPANY)</option><option value="FACTORY">Xí nghiệp (FACTORY)</option></select>
          </label>
          {b.scope_type === "FACTORY" && (
            <label className="block text-xs text-slate-500">Áp dụng cho
              <select className={cls} value={b.scope_value} onChange={(e) => setB({ ...b, scope_value: e.target.value })}><option value="">Mọi xí nghiệp</option>{factories.map((f) => <option key={f}>{f}</option>)}</select>
            </label>
          )}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
          <button onClick={() => onCreate(b)} disabled={!b.layout_code || !b.layout_name} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Tạo</button>
        </div>
      </div>
    </div>
  );
}
