import { CSSProperties, Fragment, MutableRefObject, useEffect, useMemo, useState } from "react";
import { DraftRow } from "../../lib/draft";
import { cellText, Col, naturalCompare, PLANNED_COLS, sortValue } from "../../lib/planColumns";
import { num } from "../../lib/format";

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
  const [sort, setSort] = useState<Sort>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [collapsed, setCollapsed] = useState<Set<string> | null>(null); // null = mặc định (chưa tùy chỉnh)
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [over, setOver] = useState<Over>(null);

  const frozenOffsets = useMemo(() => {
    let left = CTRL_W;
    const m = new Map<string, number>();
    cols.forEach((c) => {
      if (c.frozen) {
        m.set(c.key, left);
        left += c.w;
      }
    });
    return m;
  }, [cols]);
  const totalWidth = CTRL_W + cols.reduce((s, c) => s + c.w, 0);
  const filterActive = Object.values(filters).some((v) => v.trim());

  // ---- nhóm Factory → Line (thứ tự dòng trong chuyền giữ theo sequence)
  const tree = useMemo(() => {
    const f = new Map<string, Map<string, DraftRow[]>>();
    rows.forEach((r) => {
      if (!f.has(r.factory_code)) f.set(r.factory_code, new Map());
      const lines = f.get(r.factory_code)!;
      if (!lines.has(r.primary_line)) lines.set(r.primary_line, []);
      lines.get(r.primary_line)!.push(r);
    });
    return [...f.entries()]
      .sort((a, b) => naturalKey(a[0], b[0]))
      .map(([xn, lines]) => ({ xn, lines: [...lines.entries()].sort((a, b) => naturalKey(a[0], b[0])).map(([line, rs]) => ({ line, rows: rs })) }));
  }, [rows]);

  // mặc định: mở mọi XN, chỉ mở chuyền đầu tiên của mỗi XN
  const isCollapsed = (key: string): boolean => {
    if (filterActive) return false;
    if (collapsed) return collapsed.has(key);
    return key.startsWith("L:") && !tree.some((f) => f.lines[0] && `L:${f.xn}|${f.lines[0].line}` === key);
  };
  const toggle = (key: string) =>
    setCollapsed((cur) => {
      const base = cur ?? new Set(tree.flatMap((f) => f.lines.slice(1).map((l) => `L:${f.xn}|${l.line}`)));
      const next = new Set(base);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const setAll = (open: boolean) => setCollapsed(open ? new Set() : new Set(tree.flatMap((f) => [`F:${f.xn}`, ...f.lines.map((l) => `L:${f.xn}|${l.line}`)])));

  // nhảy tới dòng (từ Validation) → mở nhóm chứa nó
  useEffect(() => {
    if (!highlightUid) return;
    const r = rows.find((x) => x.row_uid === highlightUid);
    if (!r) return;
    setCollapsed((cur) => {
      const base = cur ?? new Set(tree.flatMap((f) => f.lines.slice(1).map((l) => `L:${f.xn}|${l.line}`)));
      const next = new Set(base);
      next.delete(`F:${r.factory_code}`);
      next.delete(`L:${r.factory_code}|${r.primary_line}`);
      return next;
    });
    setFilters({});
    setSort(null);
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
          <p className="text-[11px] text-slate-500">
            {filterActive ? `${visibleCount.toLocaleString("vi-VN")} / ` : ""}{rows.length.toLocaleString("vi-VN")} dòng ·{" "}
            {editable ? (sort ? "đang sắp xếp theo cột — bỏ sắp xếp để kéo thả đổi thứ tự" : "kéo tay cầm ⠿ để đổi thứ tự / chuyền / XN, hoặc thả PO từ Unplanned vào giữa các dòng") : "View Mode"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {selected.size > 0 && (
            <span className="rounded-lg bg-indigo-500/20 px-2.5 py-1 text-indigo-200">
              {selected.size} dòng đã chọn · SL {num(selectedQty)} <button onClick={() => setSelected(new Set())} className="ml-1 underline">bỏ chọn</button>
            </span>
          )}
          {sort && <button onClick={() => setSort(null)} className="rounded-md border border-slate-300 px-2 py-1">Bỏ sắp xếp</button>}
          {filterActive && <button onClick={() => setFilters({})} className="rounded-md border border-slate-300 px-2 py-1">Xóa lọc cột</button>}
          <button onClick={() => setAll(true)} className="rounded-md border border-slate-300 px-2 py-1">Mở tất cả</button>
          <button onClick={() => setAll(false)} className="rounded-md border border-slate-300 px-2 py-1">Thu gọn tất cả</button>
        </div>
      </div>

      <div className="pg max-h-[62vh] overflow-auto">
        <table style={{ width: totalWidth }}>
          <colgroup>
            <col style={{ width: CTRL_W }} />
            {cols.map((c) => <col key={c.key} style={{ width: c.w }} />)}
          </colgroup>
          <thead>
            <tr className="pg-h1">
              <th className="frozen" style={{ left: 0 }}>
                <input type="checkbox" aria-label="Chọn tất cả dòng đang hiển thị" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(allVisible.map((r) => r.row_uid)))} />
              </th>
              {cols.map((c) => (
                <th key={c.key} className={`${c.frozen ? "frozen" : ""} ${c.kind === "num" ? "pg-r" : ""}`} style={frozenStyle(c)} onClick={() => clickSort(c.key)} title="Bấm để sắp xếp">
                  {c.label} {sort?.key === c.key ? (sort.dir === 1 ? "▲" : "▼") : ""}
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
                    f.lines.map((l) => {
                      const lKey = `L:${f.xn}|${l.line}`;
                      const lCollapsed = isCollapsed(lKey);
                      const shown = visibleLane(l.rows);
                      if (filterActive && shown.length === 0) return null;
                      const headKey = `${lKey}#head`;
                      const endKey = `${lKey}#end`;
                      return (
                        <Fragment key={lKey}>
                          <tr className={`pg-gl ${over?.key === headKey ? "pg-drop-before" : ""}`} onClick={() => toggle(lKey)} {...dropProps(f.xn, l.line, headKey, l.rows, null)}>
                            <td colSpan={cols.length + 1}>
                              <div className="pg-gin" style={{ paddingLeft: 22 }}>
                                <span className="pg-caret">{lCollapsed ? "▶" : "▼"}</span> Chuyền <b>{l.line}</b>
                                <span className="pg-meta">{shown.length} dòng · SL {num(shown.reduce((s, r) => s + r.quantity, 0))} · Worker {num(shown.reduce((s, r) => s + (r.ref?.worker ?? 0), 0))}</span>
                                {editable && (
                                  <button
                                    className="pg-btn"
                                    style={{ marginLeft: 12, padding: "1px 10px" }}
                                    title="Tính lại ngày theo công thức cho cả chuyền (ô đang ghi đè được giữ nguyên)"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onRecalc(f.xn, l.line, null);
                                    }}
                                  >
                                    Tính lại chuyền
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                          {!lCollapsed &&
                            shown.map((r) => {
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
                                    className={`pg-row ${over?.key === rowKey ? (over.pos === "before" ? "pg-drop-before" : "pg-drop-after") : ""} ${highlightUid === r.row_uid ? "animate-blink" : ""}`}
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
                          {!lCollapsed && editable && canReorder && !filterActive && (
                            <tr className={`pg-end ${over?.key === endKey ? "pg-drop-before" : ""}`} {...dropProps(f.xn, l.line, endKey, l.rows, null)}>
                              <td colSpan={cols.length + 1}><div className="pg-gin" style={{ paddingLeft: 44 }}>thả vào đây = cuối chuyền {l.line}</div></td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
