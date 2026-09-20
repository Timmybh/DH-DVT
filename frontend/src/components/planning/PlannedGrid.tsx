import { CSSProperties, Fragment, MutableRefObject, useEffect, useMemo, useState } from "react";
import { DraftRow } from "../../lib/draft";
import { cellText, Col, naturalCompare, PLANNED_COLS, sortValue } from "../../lib/planColumns";
import { num } from "../../lib/format";
import { useColumnWidths } from "../../lib/useColumnWidths";
import { inWindow, isoWeek, periodTitle, PlanView, rangeOf, shift, startOfDay, weekRange } from "../../lib/weeks";

export type DragInfo = { kind: "unplanned"; id: number } | { kind: "returned"; uid: string } | { kind: "row"; uid: string } | null;

interface Props {
  rows: DraftRow[];
  editable: boolean;
  drag: MutableRefObject<DragInfo>;
  onDropAt: (xn: string, line: string, afterUid: string | null) => void;
  onOpenRow: (row: DraftRow) => void;
  onRecalc: (xn: string, line: string, fromUid: string | null) => void;
  highlightUid: string | null;
  issueMap: Map<string, "ERROR" | "WARNING">;
}

const CTRL_W = 92;
const naturalKey = (a: string, b: string) => naturalCompare(a, b);
type Sort = { key: string; dir: 1 | -1 } | null;
type Over = { key: string; pos: "before" | "after" } | null;

const RISK_TONE: Record<string, string> = { LATE: "#3d1b27", MATERIAL: "#3b3115", ADVANCE: "#152f4a" };
const RISK_LABEL: Record<string, string> = { LATE: "Nguy cơ trễ", MATERIAL: "Thiếu NPL", ADVANCE: "Sớm" };

function onTimeClass(v: string | undefined): string {
  const t = (v ?? "").toUpperCase();
  if (t.includes("ON TIME")) return "pg-chip pg-ok";
  if (t.includes("ADV")) return "pg-chip pg-adv";
  if (t) return "pg-chip pg-late";
  return "";
}

export default function PlannedGrid({ rows, editable, drag, onDropAt, onOpenRow, onRecalc, highlightUid, issueMap }: Props) {
  const cols = PLANNED_COLS;
  const cw = useColumnWidths("dvt_cols_planned", cols.map((c) => ({ key: c.key, w: c.w })));
  const [sort, setSort] = useState<Sort>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [collapsed, setCollapsed] = useState<Set<string> | null>(null); // null = mặc định (chưa tùy chỉnh)
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [over, setOver] = useState<Over>(null);
  // Cửa sổ thời gian: mặc định TUẦN hiện tại; có thể chọn Tháng hoặc Tất cả và nhảy trái/phải giữa các kỳ
  const [view, setViewState] = useState<PlanView>(() => {
    try {
      const v = localStorage.getItem("dvt_plan_view");
      return v === "MONTH" || v === "ALL" ? v : "WEEK";
    } catch {
      return "WEEK";
    }
  });
  const [anchor, setAnchor] = useState<Date>(() => startOfDay(new Date()));
  const setView = (v: PlanView) => {
    setViewState(v);
    try {
      localStorage.setItem("dvt_plan_view", v);
    } catch {
      /* ignore */
    }
  };
  const win = useMemo(() => rangeOf(view, anchor), [view, anchor]);
  const period = periodTitle(view, anchor);
  // dòng đang sửa trong bản nháp (mới/đã dời/đã sửa) luôn hiển thị dù nằm ngoài kỳ đang xem
  const windowRows = useMemo(() => (win ? rows.filter((r) => r._flag || inWindow(r.begin_prod_date, r.end_prod_date, win)) : rows), [rows, win]);
  const fullLanes = useMemo(() => {
    const m = new Map<string, DraftRow[]>();
    rows.forEach((r) => {
      const k = `${r.factory_code}|${r.primary_line}`;
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(r);
    });
    return m;
  }, [rows]);

  const frozenOffsets = useMemo(() => {
    let left = CTRL_W;
    const m = new Map<string, number>();
    cols.forEach((c) => {
      if (c.frozen) {
        m.set(c.key, left);
        left += cw.widthOf(c.key);
      }
    });
    return m;
  }, [cols, cw]);
  const totalWidth = CTRL_W + cols.reduce((s, c) => s + cw.widthOf(c.key), 0);
  const filterActive = Object.values(filters).some((v) => v.trim());

  // ---- nhóm Factory → Line (thứ tự dòng trong chuyền giữ theo sequence)
  const tree = useMemo(() => {
    const f = new Map<string, Map<string, DraftRow[]>>();
    windowRows.forEach((r) => {
      if (!f.has(r.factory_code)) f.set(r.factory_code, new Map());
      const lines = f.get(r.factory_code)!;
      if (!lines.has(r.primary_line)) lines.set(r.primary_line, []);
      lines.get(r.primary_line)!.push(r);
    });
    return [...f.entries()]
      .sort((a, b) => naturalKey(a[0], b[0]))
      .map(([xn, lines]) => ({ xn, lines: [...lines.entries()].sort((a, b) => naturalKey(a[0], b[0])).map(([line, rs]) => ({ line, rows: rs })) }));
  }, [windowRows]);

  // Chỉ nhóm theo Factory (không nhóm theo chuyền/tổ). Kế hoạch lớn (> 4.000 dòng) mặc định chỉ mở XN đầu tiên cho nhẹ.
  const isCollapsed = (key: string): boolean => {
    if (filterActive) return false;
    if (collapsed) return collapsed.has(key);
    return windowRows.length > 4000 && tree[0] !== undefined && key !== `F:${tree[0].xn}`;
  };
  const toggle = (key: string) =>
    setCollapsed((cur) => {
      const base = cur ?? new Set(tree.filter((f) => isCollapsed(`F:${f.xn}`)).map((f) => `F:${f.xn}`));
      const next = new Set(base);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const setAll = (open: boolean) => setCollapsed(open ? new Set() : new Set(tree.map((f) => `F:${f.xn}`)));

  // nhảy tới dòng (từ Validation) → mở nhóm chứa nó
  useEffect(() => {
    if (!highlightUid) return;
    const r = rows.find((x) => x.row_uid === highlightUid);
    if (!r) return;
    setCollapsed((cur) => {
      const base = cur ?? new Set(tree.filter((f) => isCollapsed(`F:${f.xn}`)).map((f) => `F:${f.xn}`));
      const next = new Set(base);
      next.delete(`F:${r.factory_code}`);
      return next;
    });
    setFilters({});
    setSort(null);
    const start = r.begin_prod_date ?? r.end_prod_date;
    if (start && view !== "ALL" && !inWindow(r.begin_prod_date, r.end_prod_date, win)) setAnchor(startOfDay(new Date(start.slice(0, 10) + "T00:00:00")));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightUid]);

  const matches = (r: DraftRow): boolean =>
    cols.every((c) => {
      const q = (filters[c.key] ?? "").trim().toLowerCase();
      return !q || cellText(c, r).toLowerCase().includes(q);
    });

  const visibleLane = (lane: DraftRow[]): DraftRow[] => {
    let out = filterActive ? lane.filter(matches) : lane;
    if (sort) {
      const col = cols.find((c) => c.key === sort.key);
      if (col) out = [...out].sort((a, b) => {
        const x = sortValue(col, a), y = sortValue(col, b);
        return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
      });
    }
    return out;
  };

  const canReorder = editable && !sort;
  const allVisible = useMemo(() => tree.flatMap((f) => f.lines.flatMap((l) => visibleLane(l.rows))), [tree, filters, sort]); // eslint-disable-line react-hooks/exhaustive-deps
  const selectedRows = rows.filter((r) => selected.has(r.row_uid));
  const selectedQty = selectedRows.reduce((s, r) => s + r.quantity, 0);

  const clickSort = (key: string) => setSort((cur) => (cur?.key !== key ? { key, dir: 1 } : cur.dir === 1 ? { key, dir: -1 } : null));
  const toggleSel = (uid: string) => setSelected((cur) => { const n = new Set(cur); n.has(uid) ? n.delete(uid) : n.add(uid); return n; });
  const toggleExp = (uid: string) => setExpanded((cur) => { const n = new Set(cur); n.has(uid) ? n.delete(uid) : n.add(uid); return n; });
  const allSelected = allVisible.length > 0 && allVisible.every((r) => selected.has(r.row_uid));

  const frozenStyle = (c: Col<DraftRow>): CSSProperties | undefined => (c.frozen ? { left: frozenOffsets.get(c.key) } : undefined);

  // ---- kéo/thả
  const dropProps = (xn: string, line: string, key: string, laneFull: DraftRow[], row: DraftRow | null) => ({
    onDragOver: (e: React.DragEvent) => {
      if (!editable || !drag.current || (row && !canReorder)) return;
      e.preventDefault();
      e.stopPropagation();
      let pos: "before" | "after" = "after";
      if (row) {
        const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
        pos = e.clientY < rect.top + rect.height / 2 ? "before" : "after";
      } else pos = "before";
      setOver((cur) => (cur?.key === key && cur.pos === pos ? cur : { key, pos }));
    },
    onDrop: (e: React.DragEvent) => {
      if (!editable || !drag.current || (row && !canReorder)) return;
      e.preventDefault();
      e.stopPropagation();
      const pos = over?.key === key ? over.pos : "after";
      setOver(null);
      if (!row) return onDropAt(xn, line, key.endsWith("#end") ? laneFull[laneFull.length - 1]?.row_uid ?? null : null);
      const idx = laneFull.findIndex((r) => r.row_uid === row.row_uid);
      onDropAt(xn, line, pos === "after" ? row.row_uid : laneFull[idx - 1]?.row_uid ?? null);
    },
  });

  const cellContent = (c: Col<DraftRow>, r: DraftRow) => {
    const text = cellText(c, r);
    if (c.key === "on_time" && text !== "—") return <span className={onTimeClass(text)}>{text}</span>;
    if (c.key === "line" && r.line_assignments.length > 1) return <span title="Dồn chuyền" className="pg-chip pg-adv">{text}</span>;
    if (c.key === "line" && r.transfer) return <span title="Chuyển chuyền" className="pg-chip pg-viol">{text}</span>;
    if (c.key === "quantity" && r.extra?.overrides && Object.keys(r.extra.overrides).length) return <>{text}</>;
    return text;
  };

  const visibleCount = allVisible.length;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm" data-testid="planned-grid">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
        <div>
          <h2 className="text-sm font-bold text-slate-900">Kế hoạch vận hành (Planned)</h2>
          <p className="mt-1 flex flex-wrap items-center gap-2" data-testid="plan-period">
            <span className="rounded-lg bg-indigo-500/20 px-3 py-1 text-base font-bold text-slate-900" data-testid="plan-period-title">{period.title}</span>
            {period.range && <span className="text-xs text-slate-500">{period.range}</span>}
          </p>
          <p className="text-[11px] text-slate-500">
            {filterActive ? `${visibleCount.toLocaleString("vi-VN")} / ` : ""}{windowRows.length.toLocaleString("vi-VN")}{view !== "ALL" ? ` / ${rows.length.toLocaleString("vi-VN")}` : ""} dòng ·{" "}
            {editable ? (sort ? "đang sắp xếp theo cột — bỏ sắp xếp để kéo thả đổi thứ tự" : "kéo tay cầm ⠿ để đổi thứ tự / chuyền / XN, hoặc thả PO từ Unplanned vào giữa các dòng") : "View Mode"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <div className="flex items-center gap-1" role="group" aria-label="Điều hướng kỳ">
            <button onClick={() => setAnchor((a) => shift(view === "ALL" ? "WEEK" : view, a, -1))} disabled={view === "ALL"} className="rounded-md border border-slate-300 px-2.5 py-1 disabled:opacity-30" aria-label={view === "MONTH" ? "Tháng trước" : "Tuần trước"} data-testid="plan-prev">◀</button>
            <button onClick={() => setAnchor(startOfDay(new Date()))} disabled={view === "ALL"} className="rounded-md border border-slate-300 px-2.5 py-1 disabled:opacity-30" data-testid="plan-today">{view === "MONTH" ? "Tháng này" : "Tuần này"}</button>
            <button onClick={() => setAnchor((a) => shift(view === "ALL" ? "WEEK" : view, a, 1))} disabled={view === "ALL"} className="rounded-md border border-slate-300 px-2.5 py-1 disabled:opacity-30" aria-label={view === "MONTH" ? "Tháng sau" : "Tuần sau"} data-testid="plan-next">▶</button>
          </div>
          <div className="flex overflow-hidden rounded-md border border-slate-300" role="group" aria-label="Kiểu xem">
            {([["WEEK", "Tuần"], ["MONTH", "Tháng"], ["ALL", "Tất cả"]] as const).map(([v, label]) => (
              <button key={v} onClick={() => setView(v)} aria-pressed={view === v} className={`px-3 py-1 ${view === v ? "bg-brand text-white" : ""}`} data-testid={`plan-view-${v}`}>{label}</button>
            ))}
          </div>
          {selected.size > 0 && (
            <span className="rounded-lg bg-indigo-500/20 px-2.5 py-1 text-indigo-200">
              {selected.size} dòng đã chọn · SL {num(selectedQty)} <button onClick={() => setSelected(new Set())} className="ml-1 underline">bỏ chọn</button>
            </span>
          )}
          {sort && <button onClick={() => setSort(null)} className="rounded-md border border-slate-300 px-2 py-1">Bỏ sắp xếp</button>}
          {filterActive && <button onClick={() => setFilters({})} className="rounded-md border border-slate-300 px-2 py-1">Xóa lọc cột</button>}
          {cw.customized && <button onClick={cw.reset} className="rounded-md border border-slate-300 px-2 py-1" title="Đặt lại độ rộng cột mặc định">Đặt lại độ rộng cột</button>}
          <button onClick={() => setAll(true)} className="rounded-md border border-slate-300 px-2 py-1">Mở tất cả</button>
          <button onClick={() => setAll(false)} className="rounded-md border border-slate-300 px-2 py-1">Thu gọn tất cả</button>
        </div>
      </div>

      <div className="pg max-h-[62vh] overflow-auto">
        <table style={{ width: totalWidth }}>
          <colgroup>
            <col style={{ width: CTRL_W }} />
            {cols.map((c) => <col key={c.key} style={{ width: cw.widthOf(c.key) }} />)}
          </colgroup>
          <thead>
            <tr className="pg-h1">
              <th className="frozen" style={{ left: 0 }}>
                <input type="checkbox" aria-label="Chọn tất cả dòng đang hiển thị" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(allVisible.map((r) => r.row_uid)))} />
              </th>
              {cols.map((c) => (
                <th key={c.key} className={`${c.frozen ? "frozen" : ""} ${c.kind === "num" ? "pg-r" : ""}`} style={frozenStyle(c)} onClick={() => clickSort(c.key)} title="Bấm để sắp xếp">
                  {c.label} {sort?.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : ""}
                  <span className="pg-rz" role="separator" aria-label={`Kéo để đổi độ rộng cột ${c.label}`} onPointerDown={(e) => cw.startResize(c.key, e)} onClick={(e) => e.stopPropagation()} />
                </th>
              ))}
            </tr>
            <tr className="pg-h2">
              <th className="frozen" style={{ left: 0 }} />
              {cols.map((c) => (
                <th key={c.key} className={c.frozen ? "frozen" : ""} style={frozenStyle(c)}>
                  <input
                    value={filters[c.key] ?? ""}
                    onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                    placeholder="lọc"
                    aria-label={`Lọc ${c.label}`}
                    className="pg-filter"
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={cols.length + 1} style={{ textAlign: "center", padding: 32 }}>Chưa có dòng kế hoạch.</td></tr>
            )}
            {rows.length > 0 && windowRows.length === 0 && (
              <tr><td colSpan={cols.length + 1} style={{ textAlign: "center", padding: 32 }} data-testid="plan-empty-window">Không có dòng nào trong {period.title.toLowerCase()} — bấm ◀ ▶ để chuyển kỳ hoặc chọn "Tất cả".</td></tr>
            )}
            {tree.map((f) => {
              const fKey = `F:${f.xn}`;
              const fRows = f.lines.flatMap((l) => l.rows);
              const fCollapsed = isCollapsed(fKey);
              const fShown = filterActive ? f.lines.reduce((s, l) => s + l.rows.filter(matches).length, 0) : fRows.length;
              if (filterActive && fShown === 0) return null;
              return (
                <Fragment key={f.xn}>
                  <tr className="pg-gf" onClick={() => toggle(fKey)}>
                    <td colSpan={cols.length + 1}>
                      <div className="pg-gin">
                        <span className="pg-caret">{fCollapsed ? "▶" : "▼"}</span> <b>{f.xn}</b>
                        <span className="pg-meta">{f.lines.length} chuyền · {fShown.toLocaleString("vi-VN")} dòng · SL {num(fRows.reduce((s, r) => s + r.quantity, 0))}</span>
                      </div>
                    </td>
                  </tr>
                  {!fCollapsed &&
                    (() => {
                      const shownRows = sort ? visibleLane(fRows) : f.lines.flatMap((l) => visibleLane(l.rows));
                      return (
                        <>
                          {shownRows.map((r, idx) => {
                              const l = { line: r.primary_line, rows: fullLanes.get(`${f.xn}|${r.primary_line}`) ?? [] };
                              const issue = issueMap.get(r.row_uid);
                              const risk = r.ref?.risk;
                              const isSel = selected.has(r.row_uid);
                              const tone = highlightUid === r.row_uid ? "#3730a3" : isSel ? "#25336d" : risk ? RISK_TONE[risk] : undefined;
                              const rowKey = `${r.row_uid}#row`;
                              const flagColor = r._flag === "NEW" ? "#22c55e" : r._flag === "MOVED" ? "#0ea5e9" : r._flag === "EDITED" ? "#fbbf24" : "transparent";
                              const overrides = Object.keys(r.extra?.overrides ?? {});
                              return (
                                <Fragment key={r.row_uid}>
                                  <tr
                                    id={`row-${r.row_uid}`}
                                    className={`pg-row ${idx > 0 && shownRows[idx - 1].primary_line !== r.primary_line ? "pg-lane-start" : ""} ${over?.key === rowKey ? (over.pos === "before" ? "pg-drop-before" : "pg-drop-after") : ""} ${highlightUid === r.row_uid ? "animate-blink" : ""}`}
                                    style={{ ["--row-bg" as string]: tone }}
                                    draggable={canReorder}
                                    onDragStart={(e) => {
                                      e.dataTransfer.setData("text/plain", r.row_uid);
                                      e.dataTransfer.effectAllowed = "move";
                                      drag.current = { kind: "row", uid: r.row_uid };
                                    }}
                                    onDragEnd={() => {
                                      drag.current = null;
                                      setOver(null);
                                    }}
                                    onDoubleClick={() => onOpenRow(r)}
                                    {...dropProps(f.xn, l.line, rowKey, l.rows, r)}
                                  >
                                    <td className="frozen pg-ctrl" style={{ left: 0, boxShadow: `inset 3px 0 0 ${flagColor}` }}>
                                      <span className={canReorder ? "pg-handle" : "pg-handle pg-off"} title={canReorder ? "Kéo để di chuyển" : ""}>⠿</span>
                                      <input type="checkbox" checked={isSel} onChange={() => toggleSel(r.row_uid)} aria-label={`Chọn PO ${r.po_number}`} />
                                      <button className="pg-exp" onClick={() => toggleExp(r.row_uid)} aria-label="Xem chi tiết dòng" aria-expanded={expanded.has(r.row_uid)}>{expanded.has(r.row_uid) ? "▾" : "▸"}</button>
                                      {issue && <span className={`pg-dot ${issue === "ERROR" ? "pg-err" : "pg-warn"}`} title={issue === "ERROR" ? "Có lỗi Recheck" : "Có cảnh báo Recheck"} />}
                                      {overrides.length > 0 && <span className="pg-ovr" title={`Ghi đè thủ công: ${overrides.join(", ")}`}>!</span>}
                                    </td>
                                    {cols.map((c) => (
                                      <td key={c.key} className={`${c.frozen ? "frozen" : ""} ${c.kind === "num" ? "pg-r" : ""}`} style={frozenStyle(c)} title={c.key === "description" ? r.description : undefined}>
                                        {cellContent(c, r)}
                                      </td>
                                    ))}
                                  </tr>
                                  {expanded.has(r.row_uid) && (
                                    <tr className="pg-detail">
                                      <td colSpan={cols.length + 1}>
                                        <div className="pg-detail-in">
                                          <dl>
                                            <div><dt>Mô tả</dt><dd>{r.description || "—"}</dd></div>
                                            <div><dt>Sport / Season</dt><dd>{r.sport || "—"} · {r.season || "—"}</dd></div>
                                            <div><dt>Line (gốc)</dt><dd>{r.line_raw || r.primary_line}{r.transfer ? ` · chuyển ${r.transfer.from} → ${r.transfer.to}` : ""}</dd></div>
                                            <div><dt>Rủi ro</dt><dd>{risk ? `${RISK_LABEL[risk] ?? "Đúng hạn"}${r.ref?.risk_reason ? ` — ${r.ref.risk_reason}` : ""}` : "—"}</dd></div>
                                            <div><dt>Ghi chú</dt><dd>{r.note || "—"}</dd></div>
                                            <div><dt>Ghi đè thủ công</dt><dd>{overrides.length ? overrides.join(", ") : "—"}</dd></div>
                                          </dl>
                                          <div className="flex flex-col gap-2">
                                            <button className="pg-btn" onClick={() => onOpenRow(r)}>{editable ? "Sửa dòng" : "Xem dòng"}</button>
                                            {editable && (
                                              <button className="pg-btn" title="Tính lại từ dòng này đến hết chuyền theo công thức" onClick={() => onRecalc(f.xn, l.line, r.row_uid)}>
                                                Tính lại từ dòng này
                                              </button>
                                            )}
                                          </div>
                                        </div>
                                      </td>
                                    </tr>
                                  )}
                                </Fragment>
                              );
                            })}
                        </>
                      );
                    })()}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
