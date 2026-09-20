import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, DashIndicator, DashLayout, DashLayoutItem, DashOptions, errorMessage, RuntimeResponse } from "../../api/client";
import DashboardCanvas from "../../components/dashboard/DashboardCanvas";
import { DashActions } from "../../components/dashboard/renderers";
import { dateTimeVi } from "../../lib/format";

const COLS = 12;
const ROW_H = 44;
const NOOP: DashActions = { month: "", drillRevenue: () => undefined, drillOrder: () => undefined, drillQa: () => undefined, drillPo: () => undefined, drillHr: () => undefined, drillSignal: () => undefined };
const STATUS_CHIP: Record<string, string> = { PUBLISHED: "pg-ok", DRAFT: "pg-adv", RETIRED: "pg-unk" };
const SECTION_LABEL: Record<string, string> = { MAIN: "Chính", RIGHT_SIDEBAR: "Thanh phải", BOTTOM: "Dưới", FULL_WIDTH: "Toàn chiều rộng" };

export function findOverlaps(items: DashLayoutItem[]): Set<string> {
  const vis = items.filter((i) => i.is_visible);
  const bad = new Set<string>();
  for (let a = 0; a < vis.length; a++)
    for (let b = a + 1; b < vis.length; b++) {
      const p = vis[a], q = vis[b];
      if (p.grid_x < q.grid_x + q.width && q.grid_x < p.grid_x + p.width && p.grid_y < q.grid_y + q.height && q.grid_y < p.grid_y + p.height) {
        bad.add(p.indicator_code);
        bad.add(q.indicator_code);
      }
    }
  return bad;
}

type Gesture = { code: string; mode: "move" | "resize"; sx: number; sy: number; ox: number; oy: number; ow: number; oh: number } | null;

interface Props {
  canEdit: boolean;
  canPublish: boolean;
}

export default function LayoutBuilder({ canEdit, canPublish }: Props) {
  const [layouts, setLayouts] = useState<DashLayout[]>([]);
  const [indicators, setIndicators] = useState<DashIndicator[]>([]);
  const [factories, setFactories] = useState<string[]>([]);
  const [opts, setOpts] = useState<DashOptions | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [layout, setLayout] = useState<DashLayout | null>(null);
  const [items, setItems] = useState<DashLayoutItem[]>([]);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [gesture, setGesture] = useState<Gesture>(null);
  const [creating, setCreating] = useState(false);
  const [preview, setPreview] = useState<{ scope: string; data: RuntimeResponse | null; error: string } | null>(null);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [cw, setCw] = useState(80);

  const editable = canEdit && layout?.status === "DRAFT";
  const nameOf = useMemo(() => new Map(indicators.map((i) => [i.indicator_code, i.indicator_name])), [indicators]);
  const overlaps = useMemo(() => findOverlaps(items), [items]);
  const unused = indicators.filter((i) => i.is_active && !items.some((it) => it.indicator_code === i.indicator_code));

  const loadLists = useCallback(async () => {
    const [l, i, o, m] = await Promise.all([
      api.get<DashLayout[]>("/admin/dashboard/layouts"), api.get<DashIndicator[]>("/admin/dashboard/indicators"),
      api.get<DashOptions>("/admin/dashboard/options"), api.get<{ factories: { code: string }[] }>("/dashboard/meta"),
    ]);
    setLayouts(l.data);
    setIndicators(i.data);
    setOpts(o.data);
    setFactories(m.data.factories.map((f) => f.code));
    return l.data;
  }, []);

  const open = useCallback(async (id: number) => {
    const r = await api.get<DashLayout>(`/admin/dashboard/layouts/${id}`);
    setSelected(id);
    setLayout(r.data);
    setItems(r.data.items ?? []);
    setDirty(false);
  }, []);

  useEffect(() => {
    loadLists()
      .then((l) => {
        const first = l.find((x) => x.status === "PUBLISHED" && x.scope_type === "COMPANY") ?? l[0];
        if (first) return open(first.id);
      })
      .catch((e) => setMsg({ ok: false, text: errorMessage(e) }));
  }, [loadLists, open]);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setCw(el.clientWidth / COLS));
    ro.observe(el);
    setCw(el.clientWidth / COLS);
    return () => ro.disconnect();
  }, [layout?.id]);

  // ---- kéo / đổi kích thước bằng pointer
  useEffect(() => {
    if (!gesture) return;
    const move = (e: PointerEvent) => {
      const dx = Math.round((e.clientX - gesture.sx) / cw);
      const dy = Math.round((e.clientY - gesture.sy) / ROW_H);
      setItems((cur) =>
        cur.map((it) => {
          if (it.indicator_code !== gesture.code) return it;
          if (gesture.mode === "move") return { ...it, grid_x: Math.max(0, Math.min(COLS - it.width, gesture.ox + dx)), grid_y: Math.max(0, gesture.oy + dy) };
          return { ...it, width: Math.max(1, Math.min(COLS - it.grid_x, gesture.ow + dx)), height: Math.max(1, gesture.oh + dy) };
        }),
      );
      setDirty(true);
    };
    const up = () => setGesture(null);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [gesture, cw]);

  const start = (e: React.PointerEvent, it: DashLayoutItem, mode: "move" | "resize") => {
    if (!editable) return;
    e.preventDefault();
    e.stopPropagation();
    setGesture({ code: it.indicator_code, mode, sx: e.clientX, sy: e.clientY, ox: it.grid_x, oy: it.grid_y, ow: it.width, oh: it.height });
  };

  const bottom = items.reduce((m, it) => Math.max(m, it.grid_y + it.height), 0);
  const addItem = (code: string, x = 0, y = bottom) => {
    const ind = indicators.find((i) => i.indicator_code === code);
    if (!ind || !editable) return;
    setItems((cur) => [...cur, { indicator_code: code, section: "MAIN", grid_x: Math.min(x, COLS - 4), grid_y: y, width: 4, height: 3, order_no: cur.length + 1, is_visible: true, collapsed: false, config_override_json: {} }]);
    setDirty(true);
  };
  const patchItem = (code: string, p: Partial<DashLayoutItem>) => {
    setItems((cur) => cur.map((it) => (it.indicator_code === code ? { ...it, ...p } : it)));
    setDirty(true);
  };
  const removeItem = (code: string) => {
    setItems((cur) => cur.filter((it) => it.indicator_code !== code));
    setDirty(true);
  };

  const ok = (text: string) => setMsg({ ok: true, text });
  const fail = (e: unknown) => setMsg({ ok: false, text: errorMessage(e) });

  const save = async (): Promise<boolean> => {
    if (!layout) return false;
    try {
      const ordered = [...items].sort((a, b) => a.grid_y - b.grid_y || a.grid_x - b.grid_x).map((it, n) => ({ ...it, order_no: n + 1 }));
      const r = await api.put<DashLayout>(`/admin/dashboard/layouts/${layout.id}`, { layout_name: layout.layout_name, items: ordered });
      setItems(r.data.items ?? []);
      setDirty(false);
      ok("Đã lưu bản nháp.");
      return true;
    } catch (e) {
      fail(e);
      return false;
    }
  };

  const clone = async () => {
    if (!layout) return;
    try {
      const r = await api.post<DashLayout>(`/admin/dashboard/layouts/${layout.id}/clone`);
      await loadLists();
      await open(r.data.id);
      ok(`Đã tạo bản nháp v${r.data.version}. Chỉnh sửa rồi Publish.`);
    } catch (e) {
      fail(e);
    }
  };

  const publish = async () => {
    if (!layout) return;
    setConfirmPublish(false);
    if (dirty && !(await save())) return;
    try {
      await api.post(`/admin/dashboard/layouts/${layout.id}/publish`);
      await loadLists();
      await open(layout.id);
      ok("Đã Publish — Dashboard dùng bố cục mới ngay; bản cũ được chuyển sang RETIRED.");
    } catch (e) {
      fail(e);
    }
  };

  const retire = async () => {
    if (!layout || !window.confirm("Retire bố cục này?")) return;
    try {
      await api.post(`/admin/dashboard/layouts/${layout.id}/retire`);
      await loadLists();
      await open(layout.id);
      ok("Đã Retire.");
    } catch (e) {
      fail(e);
    }
  };

  const runPreview = async (scope: string) => {
    if (!layout) return;
    if (dirty && editable && !(await save())) return;
    setPreview({ scope, data: null, error: "" });
    try {
      const r = await api.get<RuntimeResponse>("/dashboard/runtime", { params: { scope, layout_id: layout.id } });
      setPreview({ scope, data: r.data, error: "" });
    } catch (e) {
      setPreview({ scope, data: null, error: errorMessage(e) });
    }
  };

  const createLayout = async (body: { layout_code: string; layout_name: string; scope_type: string; scope_value: string }) => {
    try {
      const r = await api.post<DashLayout>("/admin/dashboard/layouts", body);
      setCreating(false);
      await loadLists();
      await open(r.data.id);
      ok("Đã tạo bản nháp mới.");
    } catch (e) {
      fail(e);
    }
  };

  const canvasHeight = (bottom + 2) * ROW_H;

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[260px_1fr]">
      <aside className="space-y-4">
        <section className="rounded-2xl border border-slate-200 bg-white p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase text-slate-400">Bố cục</h3>
            {canEdit && <button onClick={() => setCreating(true)} className="text-xs text-brand hover:underline">+ Bố cục mới</button>}
          </div>
          <ul className="max-h-56 space-y-1 overflow-y-auto">
            {layouts.map((l) => (
              <li key={l.id}>
                <button
                  onClick={() => (dirty && !window.confirm("Bỏ thay đổi chưa lưu?") ? undefined : open(l.id))}
                  className={`flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-xs ${selected === l.id ? "bg-brand/20" : "hover:bg-slate-500/10"}`}
                  data-testid={`layout-${l.layout_code}-v${l.version}`}
                >
                  <span className="min-w-0 truncate"><b>{l.layout_code}</b> v{l.version}<span className="block text-[10px] text-slate-400">{l.scope_type}{l.scope_value ? `:${l.scope_value}` : ""}</span></span>
                  <span className={`pg-chip ${STATUS_CHIP[l.status]}`}>{l.status}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-3">
          <h3 className="mb-2 text-xs font-bold uppercase text-slate-400">Chỉ số chưa đưa vào bố cục</h3>
          {unused.length === 0 && <p className="text-xs text-slate-400">Tất cả chỉ số đang hoạt động đã có trong bố cục.</p>}
          <ul className="space-y-1">
            {unused.map((i) => (
              <li
                key={i.indicator_code}
                draggable={editable}
                onDragStart={(e) => e.dataTransfer.setData("text/plain", i.indicator_code)}
                className={`flex items-center justify-between rounded-lg border border-slate-200 px-2 py-1.5 text-xs ${editable ? "cursor-grab" : "opacity-60"}`}
                data-testid={`avail-${i.indicator_code}`}
              >
                <span className="min-w-0 truncate">⠿ {i.indicator_name}</span>
                {editable && <button onClick={() => addItem(i.indicator_code)} className="ml-2 shrink-0 text-brand hover:underline">Thêm</button>}
              </li>
            ))}
          </ul>
        </section>
      </aside>

      <div className="min-w-0 space-y-3">
        {layout && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-base font-bold text-slate-900">
                {layout.layout_name} <span className="text-slate-400">· {layout.layout_code} v{layout.version}</span> <span className={`pg-chip ${STATUS_CHIP[layout.status]}`}>{layout.status}</span>
              </h2>
              <p className="text-xs text-slate-500">
                Phạm vi {layout.scope_type}{layout.scope_value ? ` (${layout.scope_value})` : ""} · lưới {COLS} cột
                {layout.published_at ? ` · Publish ${dateTimeVi(layout.published_at)} bởi ${layout.published_by}` : ""}
                {layout.status !== "DRAFT" ? " · bất biến — Clone để chỉnh sửa" : ""}
              </p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <button onClick={() => runPreview("TONG")} className="rounded-full border border-slate-300 px-3 py-1.5">Preview Tổng công ty</button>
              <button onClick={() => runPreview(factories[0] ?? "XN1")} className="rounded-full border border-slate-300 px-3 py-1.5">Preview XN</button>
              {canEdit && layout.status !== "DRAFT" && <button onClick={clone} className="rounded-full border border-slate-300 px-3 py-1.5">Tạo bản nháp từ bản này</button>}
              {editable && <button onClick={save} disabled={!dirty} className="rounded-full border border-slate-300 px-3 py-1.5 disabled:opacity-40">Lưu bản nháp</button>}
              {editable && canPublish && (
                <button onClick={() => setConfirmPublish(true)} disabled={overlaps.size > 0 || items.filter((i) => i.is_visible).length === 0} className="rounded-full bg-brand px-4 py-1.5 font-semibold text-white disabled:opacity-40">
                  Publish
                </button>
              )}
              {canPublish && layout.status === "PUBLISHED" && <button onClick={retire} className="rounded-full border border-red-400/60 px-3 py-1.5 text-red-600">Retire</button>}
            </div>
          </div>
        )}
        {msg && <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}
        {overlaps.size > 0 && <p className="rounded-lg border border-red-300/50 px-3 py-2 text-xs text-red-700" role="alert">Các ô đang chồng lấn (viền đỏ): {[...overlaps].map((c) => nameOf.get(c) ?? c).join(", ")} — sửa trước khi Publish.</p>}

        {layout ? (
          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
            <div
              ref={canvasRef}
              className="relative w-full select-none"
              style={{ height: canvasHeight, backgroundImage: `linear-gradient(to right, rgba(148,163,184,.14) 1px, transparent 1px), linear-gradient(to bottom, rgba(148,163,184,.14) 1px, transparent 1px)`, backgroundSize: `${cw}px ${ROW_H}px` }}
              data-testid="layout-canvas"
              onDragOver={(e) => editable && e.preventDefault()}
              onDrop={(e) => {
                if (!editable) return;
                e.preventDefault();
                const code = e.dataTransfer.getData("text/plain");
                const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                if (unused.some((u) => u.indicator_code === code)) addItem(code, Math.max(0, Math.floor((e.clientX - rect.left) / cw)), Math.max(0, Math.floor((e.clientY - rect.top) / ROW_H)));
              }}
            >
              {items.map((it) => {
                const bad = overlaps.has(it.indicator_code);
                return (
                  <div
                    key={it.indicator_code}
                    data-testid={`box-${it.indicator_code}`}
                    className={`absolute overflow-hidden rounded-lg border-2 text-xs ${bad ? "border-red-500 bg-red-500/15" : it.is_visible ? "border-indigo-400/70 bg-indigo-500/20" : "border-slate-500/40 bg-slate-500/10 opacity-60"}`}
                    style={{ left: it.grid_x * cw + 2, top: it.grid_y * ROW_H + 2, width: it.width * cw - 4, height: it.height * ROW_H - 4 }}
                  >
                    <div onPointerDown={(e) => start(e, it, "move")} className={`flex items-center justify-between gap-1 px-2 py-1 font-semibold ${editable ? "cursor-grab touch-none" : ""}`}>
                      <span className="truncate">{nameOf.get(it.indicator_code) ?? it.indicator_code}</span>
                      {editable && (
                        <span className="flex shrink-0 items-center gap-1" onPointerDown={(e) => e.stopPropagation()}>
                          <button title={it.is_visible ? "Ẩn" : "Hiện"} aria-label={`${it.is_visible ? "Ẩn" : "Hiện"} ${it.indicator_code}`} onClick={() => patchItem(it.indicator_code, { is_visible: !it.is_visible })}>{it.is_visible ? "👁" : "🚫"}</button>
                          <button title="Gỡ khỏi bố cục" aria-label={`Gỡ ${it.indicator_code}`} onClick={() => removeItem(it.indicator_code)}>✕</button>
                        </span>
                      )}
                    </div>
                    <div className="px-2 text-[10px] text-slate-400">
                      x{it.grid_x} y{it.grid_y} · {it.width}×{it.height}
                      {editable && opts ? (
                        <select value={it.section} onChange={(e) => patchItem(it.indicator_code, { section: e.target.value })} onPointerDown={(e) => e.stopPropagation()} className="ml-2 rounded border border-slate-500/40 bg-transparent px-1 text-[10px]" aria-label={`Khu vực ${it.indicator_code}`}>
                          {opts.sections.map((s) => <option key={s} value={s}>{SECTION_LABEL[s] ?? s}</option>)}
                        </select>
                      ) : (
                        <span className="ml-2">{SECTION_LABEL[it.section] ?? it.section}</span>
                      )}
                    </div>
                    {editable && (
                      <span onPointerDown={(e) => start(e, it, "resize")} className="absolute bottom-0 right-0 h-4 w-4 cursor-nwse-resize touch-none" title="Đổi kích thước" data-testid={`resize-${it.indicator_code}`} style={{ background: "linear-gradient(135deg, transparent 50%, rgba(129,140,248,.9) 50%)" }} />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-500">Chọn một bố cục ở bên trái.</p>
        )}
        <p className="text-[11px] text-slate-400">Kéo tiêu đề ô để di chuyển, kéo góc phải dưới để đổi kích thước (lưới {COLS} cột × {ROW_H}px). Người dùng thường chỉ thấy bản Published; bản nháp chỉ xem được bằng Preview.</p>
      </div>

      {creating && <NewLayoutModal factories={factories} onClose={() => setCreating(false)} onCreate={createLayout} />}

      {confirmPublish && layout && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="text-lg font-bold text-slate-900">Publish bố cục?</h3>
            <p className="mt-2 text-sm text-slate-600">
              {layout.layout_code} v{layout.version} sẽ trở thành bố cục mặc định cho phạm vi {layout.scope_type}
              {layout.scope_value ? ` (${layout.scope_value})` : ""} và áp dụng ngay cho mọi người dùng. Bản Published trước đó chuyển sang RETIRED. Bản đã Publish là bất biến.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => setConfirmPublish(false)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
              <button onClick={publish} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white">Xác nhận Publish</button>
            </div>
          </div>
        </div>
      )}

      {preview && (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4" role="dialog" aria-modal="true" onClick={() => setPreview(null)}>
          <div className="my-4 w-full max-w-6xl rounded-2xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-base font-bold text-slate-900">Preview — {layout?.layout_code} v{layout?.version}</h3>
              <div className="flex gap-2 text-xs">
                {["TONG", ...factories].map((s) => (
                  <button key={s} onClick={() => runPreview(s)} className={`rounded-full px-3 py-1 ${preview.scope === s ? "bg-brand text-white" : "border border-slate-300"}`}>{s === "TONG" ? "Tổng công ty" : s}</button>
                ))}
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
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="mb-4 text-lg font-bold text-slate-900">Bố cục mới (bản nháp)</h3>
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
