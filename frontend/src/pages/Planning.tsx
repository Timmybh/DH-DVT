import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, EditSessionView, errorMessage, PlanRowDto, PlanVersion, RecheckResult, UnplannedDto } from "../api/client";
import PendingDropModal from "../components/planning/PendingDropModal";
import ConfirmMoveModal, { PendingMove } from "../components/planning/ConfirmMoveModal";
import PlannedGrid, { DragInfo } from "../components/planning/PlannedGrid";
import RowEditorModal from "../components/planning/RowEditorModal";
import UnplannedPanel from "../components/planning/UnplannedPanel";
import ValidationPanel from "../components/planning/ValidationPanel";
import { useAuth } from "../context/AuthContext";
import { applyOpsLocal, DraftRow, loadDraft, newTempId, Op, saveDraft } from "../lib/draft";
import { dateTimeVi } from "../lib/format";

const MAX_UNDO = 100;
const HEARTBEAT_MS = 30_000;

type Notice = { ok: boolean; text: string } | null;

export default function Planning() {
  const { can } = useAuth();
  const [versions, setVersions] = useState<PlanVersion[]>([]);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [baseRows, setBaseRows] = useState<PlanRowDto[]>([]);
  const [loadingRows, setLoadingRows] = useState(false);
  const [factories, setFactories] = useState<string[]>([]);
  const [other, setOther] = useState<EditSessionView | null>(null);
  const [session, setSession] = useState<EditSessionView | null>(null);
  const [sessionLost, setSessionLost] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);
  const [notice, setNotice] = useState<Notice>(null);

  // ---- Draft State (§3)
  const [ops, setOps] = useState<Op[]>([]);
  const [undoStack, setUndoStack] = useState<Op[][]>([]);
  const [redoStack, setRedoStack] = useState<Op[][]>([]);
  const [revision, setRevision] = useState(0);
  const [recheck, setRecheck] = useState<RecheckResult | null>(null);
  const [recheckRev, setRecheckRev] = useState(-1);
  const [busy, setBusy] = useState("");
  const [unplannedMap, setUnplannedMap] = useState<Map<number, UnplannedDto>>(new Map());
  const [returnedMap, setReturnedMap] = useState<Map<string, UnplannedDto>>(new Map());
  const [pendingMove, setPendingMove] = useState<PendingMove | null>(null);
  const [unplannedReload, setUnplannedReload] = useState(0);
  const drag = useRef<DragInfo>(null);
  const [pending, setPending] = useState<{ source: UnplannedDto; xn: string; line: string; afterUid: string | null } | null>(null);
  const [openRow, setOpenRow] = useState<DraftRow | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [showCommit, setShowCommit] = useState(false);
  const [commitNote, setCommitNote] = useState("");
  const [commitKind, setCommitKind] = useState<"F" | "V">("F");
  const [baselineFrom, setBaselineFrom] = useState("");

  const editing = !!session && !sessionLost;
  const version = versions.find((v) => v.id === versionId) ?? null;

  const computedMap = useMemo(() => new Map((recheck?.computed_rows ?? []).map((r) => [r.row_uid, r])), [recheck]);
  const returnedSnap = useMemo(() => new Map([...returnedMap].map(([uid, d]) => [uid, d.snapshot as PlanRowDto])), [returnedMap]);
  const draft = useMemo(
    () => applyOpsLocal(baseRows, unplannedMap, ops, recheckRev >= 0 ? computedMap : new Map(), returnedSnap),
    [baseRows, unplannedMap, ops, computedMap, recheckRev, returnedSnap],
  );
  const draftRows = draft.rows;
  // dòng vừa trả về Unplanned trong bản nháp → hiện đầu bảng Unplanned
  const draftReturned = useMemo<UnplannedDto[]>(
    () =>
      draft.returned.map((r, i) => ({
        id: -1000 - i, returned: true, row_uid: r.row_uid, snapshot: r, ref: r.ref, source_key: r.source_key, factory_code: r.factory_code,
        factory_assignment: "KNOWN", mapping_status: "OK", mapping_note: "", fac_raw: r.factory_code, po_number: r.po_number, style_cc: r.style_cc,
        model_code: r.model_code, description: r.description, customer: r.customer, sport: r.sport, season: r.season, quantity: r.quantity,
        capacity: r.capacity, chd: r.chd, note: r.note, po_date: null,
      })),
    [draft.returned],
  );
  const excludeReturned = useMemo(() => new Set(ops.filter((o) => o.type === "ADD_RETURNED").map((o) => (o as Extract<Op, { type: "ADD_RETURNED" }>).rowUid)), [ops]);
  const stale = recheck !== null && recheckRev !== revision;
  const excludeIds = useMemo(() => new Set(ops.filter((o) => o.type === "ADD_FROM_UNPLANNED").map((o) => (o as Extract<Op, { type: "ADD_FROM_UNPLANNED" }>).sourceId)), [ops]);

  const issueMap = useMemo(() => {
    const m = new Map<string, "ERROR" | "WARNING">();
    if (recheck && !stale) recheck.issues.forEach((i) => m.set(i.row_uid, i.severity === "ERROR" || m.get(i.row_uid) === "ERROR" ? "ERROR" : "WARNING"));
    return m;
  }, [recheck, stale]);

  const overridesList = useMemo(
    () => draftRows.filter((r) => Object.keys(r.extra?.overrides ?? {}).length).map((r) => ({ row_uid: r.row_uid, po_number: r.po_number, fields: Object.keys(r.extra.overrides ?? {}) })),
    [draftRows],
  );

  const linesByFactory = useMemo(() => {
    const m = new Map<string, string[]>();
    draftRows.forEach((r) => {
      const arr = m.get(r.factory_code) ?? [];
      if (!arr.includes(r.primary_line)) arr.push(r.primary_line);
      m.set(r.factory_code, arr);
    });
    m.forEach((v) => v.sort((a, b) => a.localeCompare(b, undefined, { numeric: true })));
    return m;
  }, [draftRows]);

  // ---------------------------------------------------------------- tải dữ liệu
  const loadVersions = useCallback(async (select?: number) => {
    const list = (await api.get<PlanVersion[]>("/planning/versions")).data;
    setVersions(list);
    setVersionId((cur) => select ?? cur ?? list.find((v) => v.status === "ISSUED")?.id ?? list[0]?.id ?? null);
  }, []);

  const loadRows = useCallback(async (id: number) => {
    setLoadingRows(true);
    try {
      let offset = 0;
      const all: PlanRowDto[] = [];
      for (;;) {
        const r = await api.get<{ total: number; rows: PlanRowDto[] }>(`/planning/versions/${id}/rows`, { params: { limit: 2000, offset } });
        all.push(...r.data.rows);
        offset += r.data.rows.length;
        if (offset >= r.data.total || r.data.rows.length === 0) break;
      }
      setBaseRows(all);
    } finally {
      setLoadingRows(false);
    }
  }, []);

  const refreshSession = useCallback(async () => {
    try {
      const a = (await api.get<{ active: EditSessionView | null }>("/planning/session/current")).data.active;
      setOther(a && !a.is_mine ? a : null);
      return a;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const meta = (await api.get<{ factories: { code: string }[] }>("/dashboard/meta")).data;
        const codes = meta.factories.map((f) => f.code);
        setFactories(codes);
        await loadVersions();
        const a = await refreshSession();
        if (a?.is_mine) {
          // khôi phục phiên của chính mình sau khi tải lại trang
          setSession(a);
          if (a.base_version_id) setVersionId(a.base_version_id);
          const saved = loadDraft();
          if (saved && saved.baseVersionId === a.base_version_id) {
            setOps(saved.ops);
            setRevision(saved.revision + 1);
          }
        }
      } catch (e) {
        setNotice({ ok: false, text: errorMessage(e) });
      }
    })();
  }, [loadVersions, refreshSession]);

  useEffect(() => {
    if (versionId) loadRows(versionId).catch((e) => setNotice({ ok: false, text: errorMessage(e) }));
  }, [versionId, loadRows]);

  // pool Unplanned: giữ cache mọi PO đã từng thấy để dựng lại Draft khi khôi phục
  const handleUnplannedRows = useCallback((rows: UnplannedDto[]) => {
    setUnplannedMap((prev) => {
      const next = new Map(prev);
      rows.filter((r) => !r.returned).forEach((r) => next.set(r.id, r));
      return next;
    });
    setReturnedMap((prev) => {
      const ret = rows.filter((r) => r.returned && r.row_uid);
      if (!ret.length) return prev;
      const next = new Map(prev);
      ret.forEach((r) => next.set(r.row_uid as string, r));
      return next;
    });
  }, []);

  // ---------------------------------------------------------------- phiên soạn thảo
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  useEffect(() => {
    if (!session || sessionLost) return;
    const t = setInterval(async () => {
      if (!navigator.onLine) return;
      try {
        await api.post(`/planning/session/${session.id}/heartbeat`);
      } catch (e) {
        const status = (e as { response?: { status?: number } }).response?.status;
        if (status === 409 || status === 403 || status === 404) setSessionLost(true);
      }
    }, HEARTBEAT_MS);
    return () => clearInterval(t);
  }, [session, sessionLost]);

  useEffect(() => {
    if (editing) return;
    const t = setInterval(refreshSession, 15_000);
    return () => clearInterval(t);
  }, [editing, refreshSession]);

  // lưu Draft cục bộ để khôi phục khi trình duyệt lỗi / mất mạng (§14)
  useEffect(() => {
    if (session && versionId) saveDraft({ baseVersionId: versionId, ops, revision, savedAt: new Date().toISOString() });
  }, [ops, revision, session, versionId]);

  async function enterEdit() {
    if (!versionId) return;
    setBusy("session");
    try {
      const r = await api.post<{ session: EditSessionView; resumed: boolean }>("/planning/session", { base_version_id: versionId });
      setSession(r.data.session);
      setSessionLost(false);
      setOther(null);
      const saved = loadDraft();
      if (ops.length === 0 && saved && saved.baseVersionId === versionId && saved.ops.length && window.confirm(`Khôi phục bản nháp chưa lưu (${saved.ops.length} thao tác)?`)) {
        setOps(saved.ops);
        setRevision(saved.revision + 1);
      } else if (sessionLost) {
        setRevision((v) => v + 1); // bản nháp cục bộ giữ nguyên, phiên mới -> cần Recheck lại
      }
      setNotice({ ok: true, text: r.data.resumed ? "Đã khôi phục phiên soạn thảo của bạn." : "Đã vào Edit Mode — chỉ bạn được chỉnh sửa lúc này." });
    } catch (e) {
      setNotice({ ok: false, text: errorMessage(e) });
      refreshSession();
    } finally {
      setBusy("");
    }
  }

  function resetDraft() {
    setOps([]);
    setUndoStack([]);
    setRedoStack([]);
    setRecheck(null);
    setRecheckRev(-1);
    setRevision(0);
    saveDraft(null);
  }

  async function cancelEdit() {
    if (ops.length && !window.confirm("Hủy chỉnh sửa và bỏ toàn bộ bản nháp?")) return;
    if (session && !sessionLost) await api.post(`/planning/session/${session.id}/release`).catch(() => undefined);
    setSession(null);
    setSessionLost(false);
    resetDraft();
    refreshSession();
  }

  async function forceUnlock() {
    if (!other || !window.confirm(`Force Unlock phiên của ${other.username}? Bản nháp của họ sẽ mất hiệu lực.`)) return;
    try {
      await api.post(`/planning/session/${other.id}/force-unlock`);
      setNotice({ ok: true, text: "Đã Force Unlock." });
      refreshSession();
    } catch (e) {
      setNotice({ ok: false, text: errorMessage(e) });
    }
  }

  // ---------------------------------------------------------------- thao tác Draft
  const pushOps = useCallback(
    (next: Op[]) => {
      setUndoStack((s) => [...s.slice(-(MAX_UNDO - 1)), ops]);
      setRedoStack([]);
      setOps(next);
      setRevision((v) => v + 1);
    },
    [ops],
  );

  const undo = useCallback(() => {
    if (!undoStack.length) return;
    setRedoStack((s) => [...s, ops]);
    setOps(undoStack[undoStack.length - 1]);
    setUndoStack((s) => s.slice(0, -1));
    setRevision((v) => v + 1);
  }, [undoStack, ops]);

  const redo = useCallback(() => {
    if (!redoStack.length) return;
    setUndoStack((s) => [...s, ops]);
    setOps(redoStack[redoStack.length - 1]);
    setRedoStack((s) => s.slice(0, -1));
    setRevision((v) => v + 1);
  }, [redoStack, ops]);

  useEffect(() => {
    if (!editing) return;
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.ctrlKey && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
      else if (e.ctrlKey && (e.key.toLowerCase() === "y" || (e.shiftKey && e.key.toLowerCase() === "z"))) { e.preventDefault(); redo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editing, undo, redo]);

  function handleDropAt(xn: string, line: string, afterUid: string | null) {
    const d = drag.current;
    drag.current = null;
    if (!d || !editing) return;
    if (d.kind === "row") {
      // Pending Drop: chỉ đổi thứ tự sau khi Xác nhận
      const row = draftRows.find((r) => r.row_uid === d.uid);
      if (!row || d.uid === afterUid) return;
      const afterPo = draftRows.find((r) => r.row_uid === afterUid)?.po_number ?? "";
      setPendingMove({ kind: "move", row, xn, line, afterUid, afterPo });
      return;
    }
    const src = d.kind === "returned" ? returnedMap.get(d.uid) ?? draftReturned.find((r) => r.row_uid === d.uid) : unplannedMap.get(d.id);
    if (!src) return;
    if (!src.returned && src.factory_assignment === "KNOWN" && src.factory_code !== xn) {
      setNotice({ ok: false, text: `PO ${src.po_number} thuộc ${src.factory_code} — chỉ thả vào chuyền của ${src.factory_code} (giữ nguyên XN đã biết).` });
      return;
    }
    setPending({ source: src, xn, line, afterUid });
  }

  function confirmPending(factory: string, line: string, moved: boolean) {
    if (!pending) return;
    const lane = draftRows.filter((r) => r.factory_code === factory && r.primary_line === line);
    const after = moved ? lane[lane.length - 1]?.row_uid ?? null : pending.afterUid;
    const src = pending.source;
    pushOps([
      ...ops,
      src.returned
        ? { type: "ADD_RETURNED", rowUid: src.row_uid as string, factory, line, afterRowUid: after }
        : { type: "ADD_FROM_UNPLANNED", tempRowId: newTempId(), sourceId: src.id, factory, line, afterRowUid: after },
    ]);
    setPending(null);
  }

  function recalcLane(xn: string, line: string, fromUid: string | null) {
    if (!editing) return;
    pushOps([...ops, { type: "RECALC_LANE", factory: xn, line, ...(fromUid ? { fromRowUid: fromUid } : {}) }]);
    setNotice({ ok: true, text: `Đã thêm thao tác "Tính lại" cho chuyền ${xn}/${line}. Bấm Recheck All Plan để xem ngày mới theo công thức.` });
  }

  function dropPlannedToUnplanned(uid: string) {
    const row = draftRows.find((r) => r.row_uid === uid);
    if (row && editing) setPendingMove({ kind: "unplan", row });
  }

  function confirmMove() {
    if (!pendingMove) return;
    if (pendingMove.kind === "move") pushOps([...ops, { type: "MOVE", rowUid: pendingMove.row.row_uid, factory: pendingMove.xn, line: pendingMove.line, afterRowUid: pendingMove.afterUid }]);
    else pushOps([...ops, { type: "UNPLAN", rowUid: pendingMove.row.row_uid }]);
    setPendingMove(null);
  }

  // ---------------------------------------------------------------- Recheck / Commit
  async function runRecheck() {
    if (!session || !versionId) return;
    setBusy("recheck");
    try {
      const r = await api.post<RecheckResult>(`/planning/session/${session.id}/recheck`, { base_version_id: versionId, ops, draft_revision: revision });
      setRecheck(r.data);
      setRecheckRev(revision);
      setNotice({ ok: r.data.result !== "ERROR", text: `Recheck All Plan: ${r.data.result} — ${r.data.counts.ERROR} lỗi, ${r.data.counts.WARNING} cảnh báo (${r.data.duration_ms} ms).` });
    } catch (e) {
      const status = (e as { response?: { status?: number } }).response?.status;
      if (status === 409) setSessionLost(true);
      setNotice({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy("");
    }
  }

  async function doCommit() {
    if (!session || !versionId) return;
    setBusy("commit");
    try {
      const r = await api.post<PlanVersion>(`/planning/session/${session.id}/commit`, { base_version_id: versionId, ops, draft_revision: revision, note: commitNote, kind: commitKind });
      setNotice({ ok: true, text: `Đã Commit phiên bản ${r.data.code} (bất biến). Muốn áp dụng cần Issue ở màn hình Phiên bản.` });
      setShowCommit(false);
      setSession(null);
      resetDraft();
      setCommitNote("");
      setUnplannedReload((k) => k + 1);
      await loadVersions(r.data.id);
    } catch (e) {
      setNotice({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy("");
    }
  }

  async function createBaseline() {
    setBusy("baseline");
    try {
      const r = await api.post("/planning/baseline", { from_date: baselineFrom || null });
      setNotice({ ok: true, text: `Đã tạo ${r.data.version.code}: ${r.data.rows.toLocaleString("vi-VN")} dòng (Recheck ${r.data.recheck}).` });
      await loadVersions(r.data.version.id);
    } catch (e) {
      setNotice({ ok: false, text: errorMessage(e) });
    } finally {
      setBusy("");
    }
  }

  function focusRow(uid: string) {
    const row = draftRows.find((r) => r.row_uid === uid);
    if (!row) return;
    setHighlight(uid);
    setTimeout(() => document.getElementById(`row-${uid}`)?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" }), 80);
    setTimeout(() => setHighlight((h) => (h === uid ? null : h)), 3500);
  }

  const commitReady = editing && online && ops.length > 0 && recheck !== null && !stale && recheck.result !== "ERROR";
  const validationLabel = !recheck ? "Chưa Recheck" : stale ? "Needs Recheck" : recheck.result;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Kế hoạch sản xuất</h1>
          <p className="text-xs text-slate-500">Planning cấp Tổng công ty — Planned ở trên, Chưa lên KH (Unplanned) ở dưới.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={versionId ?? ""}
            disabled={editing}
            onChange={(e) => setVersionId(Number(e.target.value))}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm shadow-sm disabled:opacity-60"
            aria-label="Phiên bản"
          >
            {versions.length === 0 && <option value="">Chưa có phiên bản</option>}
            {versions.map((v) => (
              <option key={v.id} value={v.id}>{v.code} · {v.status}</option>
            ))}
          </select>
          {version && (
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${version.status === "ISSUED" ? "bg-green-100 text-green-700" : version.status === "SUPERSEDED" ? "bg-slate-100 text-slate-500" : "bg-sky-100 text-sky-700"}`}>
              {version.status}
            </span>
          )}
        </div>
      </div>

      {notice && (
        <div className={`flex items-start justify-between rounded-xl border p-3 text-sm ${notice.ok ? "border-green-200 bg-green-50 text-green-800" : "border-red-200 bg-red-50 text-red-700"}`}>
          <span>{notice.text}</span>
          <button onClick={() => setNotice(null)} className="ml-3 text-slate-400 hover:text-slate-700">✕</button>
        </div>
      )}

      {/* Thanh chế độ */}
      {editing ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-sm" data-testid="edit-bar">
          <div className="flex items-center gap-3">
            <span className="rounded-full bg-brand px-2.5 py-0.5 text-xs font-bold text-white">EDIT MODE</span>
            <span className="text-indigo-900">{ops.length} thao tác · Validation: <b>{validationLabel}</b></span>
            {!online && <span className="rounded bg-red-100 px-2 py-0.5 text-xs font-bold text-red-700">OFFLINE — vẫn sửa được, tạm khóa Recheck/Commit</span>}
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={undo} disabled={!undoStack.length} className="rounded-lg border border-indigo-200 bg-white px-3 py-1 text-xs font-medium disabled:opacity-40" title="Ctrl+Z">Undo</button>
            <button onClick={redo} disabled={!redoStack.length} className="rounded-lg border border-indigo-200 bg-white px-3 py-1 text-xs font-medium disabled:opacity-40" title="Ctrl+Y">Redo</button>
            <button onClick={() => window.confirm("Hoàn tác toàn bộ thay đổi trong bản nháp?") && pushOps([])} disabled={!ops.length} className="rounded-lg border border-indigo-200 bg-white px-3 py-1 text-xs font-medium disabled:opacity-40">Revert All</button>
            {can("planning.recheck") && (
              <button onClick={runRecheck} disabled={busy !== "" || !online} className="rounded-lg bg-slate-800 px-3 py-1 text-xs font-semibold text-white disabled:opacity-40">
                {busy === "recheck" ? "Đang Recheck..." : "Recheck All Plan"}
              </button>
            )}
            {can("planning.commit") && (
              <button onClick={() => setShowCommit(true)} disabled={!commitReady} title={commitReady ? "" : "Cần Recheck (không ERROR) đúng bản nháp hiện tại"} className="rounded-lg bg-brand px-3 py-1 text-xs font-semibold text-white disabled:opacity-40">
                Commit
              </button>
            )}
            <button onClick={cancelEdit} className="rounded-lg border border-slate-300 bg-white px-3 py-1 text-xs font-medium">Cancel Edit</button>
          </div>
        </div>
      ) : sessionLost && session ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          <span>Phiên soạn thảo đã hết hiệu lực (mất heartbeat hoặc bị Force Unlock). Bản nháp cục bộ ({ops.length} thao tác) vẫn được giữ — vào lại Edit Mode để tiếp tục, rồi Recheck và Commit.</span>
          <div className="flex gap-2">
            <button onClick={enterEdit} className="rounded-lg bg-brand px-3 py-1 text-xs font-semibold text-white">Vào lại Edit Mode</button>
            <button onClick={cancelEdit} className="rounded-lg border border-red-300 bg-white px-3 py-1 text-xs">Bỏ bản nháp</button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm shadow-sm">
          <div className="flex items-center gap-3 text-slate-600">
            <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-bold text-slate-500">VIEW MODE</span>
            {other ? (
              <span>Đang được <b>{other.username}</b> chỉnh sửa từ {dateTimeVi(other.started_at)} — bạn chỉ có thể xem.</span>
            ) : (
              <span>{version ? `${version.code} · ${version.row_count.toLocaleString("vi-VN")} dòng · Recheck ${version.recheck_result || "—"}` : "Chưa có phiên bản kế hoạch"}</span>
            )}
          </div>
          <div className="flex gap-2">
            {other && can("planning.force_unlock") && (
              <button onClick={forceUnlock} className="rounded-lg border border-red-300 bg-red-50 px-3 py-1 text-xs font-semibold text-red-700">Force Unlock</button>
            )}
            {can("planning.edit") && version && !other && (
              <button onClick={enterEdit} disabled={busy !== "" || loadingRows} className="rounded-lg bg-brand px-4 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50">
                Vào Edit Mode
              </button>
            )}
          </div>
        </div>
      )}

      {/* Chưa có phiên bản nào: tạo nền từ file Excel đã nhập */}
      {versions.length === 0 && (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-6 text-center">
          <p className="text-sm text-slate-600">Chưa có phiên bản kế hoạch. Tạo phiên bản nền từ file Excel kế hoạch SX đã nhập (chỉ lấy dòng có XN và chuyền hợp lệ).</p>
          {can("planning.commit") && (
            <div className="mt-3 flex items-center justify-center gap-2">
              <label className="text-xs text-slate-500">Chỉ lấy dòng kết thúc từ ngày <input type="date" value={baselineFrom} onChange={(e) => setBaselineFrom(e.target.value)} className="ml-1 rounded border border-slate-200 px-2 py-1 text-sm" /></label>
              <button onClick={createBaseline} disabled={busy !== ""} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
                {busy === "baseline" ? "Đang tạo..." : "Tạo phiên bản nền"}
              </button>
            </div>
          )}
        </div>
      )}

      {version && (
        <>
          {loadingRows && <p className="text-sm text-slate-500">Đang tải kế hoạch...</p>}
          <PlannedGrid
            rows={draftRows}
            editable={editing}
            drag={drag}
            onDropAt={handleDropAt}
            onOpenRow={setOpenRow}
            onRecalc={recalcLane}
            highlightUid={highlight}
            issueMap={issueMap}
          />
          <UnplannedPanel
            baseVersionId={versionId}
            factories={factories}
            editable={editing}
            excludeIds={excludeIds}
            excludeReturned={excludeReturned}
            extraRows={draftReturned}
            reloadKey={unplannedReload}
            drag={drag}
            onRows={handleUnplannedRows}
            onDropPlanned={dropPlannedToUnplanned}
          />
        </>
      )}

      {editing && <ValidationPanel result={recheck} stale={stale} overrides={overridesList} onFocus={focusRow} />}

      {pending && (
        <PendingDropModal
          source={pending.source}
          factories={factories}
          linesByFactory={linesByFactory}
          initialFactory={pending.xn}
          initialLine={pending.line}
          onConfirm={confirmPending}
          onCancel={() => setPending(null)}
        />
      )}

      {pendingMove && <ConfirmMoveModal pending={pendingMove} onConfirm={confirmMove} onCancel={() => setPendingMove(null)} />}

      {openRow && <RowEditorModal row={openRow} editable={editing} onApply={(o) => pushOps([...ops, ...o])} onClose={() => setOpenRow(null)} />}

      {showCommit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="text-lg font-bold text-slate-900">Commit phiên bản</h3>
            <p className="mt-1 text-xs text-slate-500">Commit tạo phiên bản BẤT BIẾN, chưa áp dụng vận hành (cần Issue riêng). Recheck: <b>{recheck?.result}</b> · {ops.length} thao tác.</p>
            <label className="mt-4 block text-xs font-medium text-slate-500">
              Loại phiên bản
              <select value={commitKind} onChange={(e) => setCommitKind(e.target.value as "F" | "V")} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm">
                <option value="F">Phương án con (f) của {version?.code}</option>
                <option value="V">Phương án tuần mới (v)</option>
              </select>
            </label>
            <label className="mt-3 block text-xs font-medium text-slate-500">
              Ghi chú
              <input value={commitNote} onChange={(e) => setCommitNote(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm" placeholder="VD: dồn PO gấp vào XN2" />
            </label>
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => setShowCommit(false)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">Hủy</button>
              <button onClick={doCommit} disabled={busy === "commit"} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
                {busy === "commit" ? "Đang commit..." : "Commit"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
