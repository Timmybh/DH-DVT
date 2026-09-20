import { useCallback, useEffect, useMemo, useState } from "react";
import { api, CaseResult, ColumnExplain, errorMessage, FormulaDef, PlanColumnCfg } from "../../api/client";
import { useAuth } from "../../context/AuthContext";
import { dateTimeVi } from "../../lib/format";

const INPUT_LABEL: Record<string, string> = { MANUAL: "Manual Input", LIST: "Select from List", CALCULATED: "Calculated" };
const STATUS_TONE: Record<string, string> = { PUBLISHED: "pg-ok", DRAFT: "pg-adv", RETIRED: "pg-unk" };

const serialToDate = (n: number): string => new Date(Date.UTC(1899, 11, 30) + n * 86400000).toLocaleDateString("vi-VN");

function show(v: unknown, type: string): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return type === "date" ? serialToDate(v) : Number(v.toFixed(6)).toLocaleString("vi-VN", { maximumFractionDigits: 6 });
  return String(v);
}

function CaseTable({ cases, type }: { cases: CaseResult[]; type: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b border-slate-100 text-slate-400">
            <th className="py-1.5">Ca chuẩn</th>
            <th>Đầu vào</th>
            <th>Kỳ vọng (workbook)</th>
            <th>Bộ tính</th>
            <th>Nguồn</th>
            <th>Kết quả</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c, i) => (
            <tr key={i} className="border-b border-slate-50 align-top">
              <td className="py-1.5 font-medium text-slate-800">{c.kind}</td>
              <td className="max-w-[260px] text-slate-500">
                {JSON.stringify({ ...(c.inputs ?? {}), ...(c.prev ? { "dòng trước": c.prev } : {}) })}
              </td>
              <td>{show(c.expected, type)}</td>
              <td>{show(c.actual, type)}</td>
              <td className="text-slate-500">{c.synthetic ? "Tổng hợp (biên/rỗng)" : `Excel dòng ${c.source_row}`}</td>
              <td>
                <span className={`pg-chip ${c.ok ? "pg-ok" : "pg-late"}`}>{c.ok ? "ĐẠT" : "LỆCH"}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Explain({ code, onClose, canManage, onChanged }: { code: string; onClose: () => void; canManage: boolean; onChanged: () => void }) {
  const [data, setData] = useState<ColumnExplain | null>(null);
  const [err, setErr] = useState("");
  const [expr, setExpr] = useState("");
  const [inputs, setInputs] = useState("{}");
  const [check, setCheck] = useState<{ ok: boolean; errors?: string[]; result?: unknown; error?: string } | null>(null);
  const [busy, setBusy] = useState("");
  const [openDef, setOpenDef] = useState<FormulaDef | null>(null);

  const load = useCallback(async () => {
    setErr("");
    try {
      const d = (await api.get<ColumnExplain>(`/planning/columns/${code}/explain`)).data;
      setData(d);
      setExpr((cur) => cur || d.current?.expression || d.versions[0]?.expression || "");
    } catch (e) {
      setErr(errorMessage(e));
    }
  }, [code]);
  useEffect(() => {
    setExpr("");
    setCheck(null);
    setOpenDef(null);
    load();
  }, [load]);

  async function validate() {
    setBusy("validate");
    try {
      setCheck((await api.post("/planning/formulas/validate", { column_code: code, expression: expr })).data);
    } catch (e) {
      setCheck({ ok: false, errors: [errorMessage(e)] });
    } finally {
      setBusy("");
    }
  }

  async function preview() {
    setBusy("preview");
    try {
      const body = JSON.parse(inputs || "{}");
      setCheck((await api.post("/planning/formulas/preview", { expression: expr, inputs: body.inputs ?? body, prev: body.prev ?? null, manual: body.manual ?? null })).data);
    } catch (e) {
      setCheck({ ok: false, error: e instanceof SyntaxError ? "JSON đầu vào không hợp lệ" : errorMessage(e) });
    } finally {
      setBusy("");
    }
  }

  async function saveDraft() {
    setBusy("draft");
    try {
      await api.post("/planning/formulas", { column_code: code, expression: expr, description: data?.current?.description ?? "", cases: [] });
      setCheck({ ok: true, result: "Đã tạo bản nháp mới. Publish cần ca chuẩn từ workbook." });
      await load();
      onChanged();
    } catch (e) {
      setCheck({ ok: false, errors: [errorMessage(e)] });
    } finally {
      setBusy("");
    }
  }

  async function publish(id: number) {
    setBusy("publish");
    try {
      await api.post(`/planning/formulas/${id}/publish`);
      setCheck({ ok: true, result: "Đã Publish." });
      await load();
      onChanged();
    } catch (e) {
      setCheck({ ok: false, errors: [errorMessage(e)] });
    } finally {
      setBusy("");
    }
  }

  const cur = data?.current;
  const shown = openDef ?? cur;
  const type = data?.column.value_type ?? "number";

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50" onClick={onClose}>
      <aside className="h-full w-full max-w-3xl overflow-y-auto bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()} aria-label="Giải thích công thức">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold text-slate-900">{data?.column.label ?? code}</h2>
            <p className="text-xs text-slate-500">
              {code} · cột workbook "{data?.column.workbook_header}" · {INPUT_LABEL[data?.column.input_type ?? "MANUAL"]}
              {data?.column.list_source ? ` · danh sách: ${data.column.list_source}` : ""}
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700" aria-label="Đóng">✕</button>
        </div>
        {err && <p className="mt-3 text-sm text-red-600">{err}</p>}

        {data && !cur && (
          <p className="mt-4 rounded-lg border border-slate-200 p-3 text-sm text-slate-600">
            Cột này chưa có công thức được Publish{data.versions.length ? " (có bản nháp bên dưới)" : ""}: giá trị do người dùng nhập/chọn hoặc lấy từ dữ liệu nguồn.
          </p>
        )}

        {shown && (
          <div className="mt-4 space-y-4">
            <section>
              <h3 className="text-xs font-bold uppercase text-slate-400">Công thức {openDef ? `(v${openDef.version} — ${openDef.status})` : `đang hiệu lực v${shown.version}`}</h3>
              <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-slate-100 p-3 font-mono text-xs text-slate-800">{shown.expression}</pre>
              <p className="mt-2 text-sm text-slate-700">{shown.description}</p>
            </section>
            <section className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-2">
              <div><p className="font-semibold text-slate-400">Công thức gốc trong workbook</p><p className="text-slate-700">{shown.workbook_formula || "—"}</p></div>
              <div><p className="font-semibold text-slate-400">Cột nguồn</p><p className="text-slate-700">{shown.source_columns || "—"}</p></div>
              <div><p className="font-semibold text-slate-400">Phụ thuộc (cùng dòng)</p><p className="text-slate-700">{shown.dependencies.columns?.join(", ") || "—"}</p></div>
              <div><p className="font-semibold text-slate-400">Tham chiếu ngữ nghĩa</p><p className="text-slate-700">{shown.dependencies.semantic?.join(", ") || "—"}</p></div>
              <div><p className="font-semibold text-slate-400">Làm tròn</p><p className="text-slate-700">{shown.rounding_policy || "—"}</p></div>
              <div><p className="font-semibold text-slate-400">Lịch làm việc</p><p className="text-slate-700">{shown.calendar_policy || "—"}</p></div>
              <div><p className="font-semibold text-slate-400">Tài liệu nguồn</p><p className="text-slate-700">{shown.source_document || "—"} · sheet {shown.source_sheet || "—"}</p></div>
              <div>
                <p className="font-semibold text-slate-400">Đối chiếu toàn bộ workbook</p>
                <p className="text-slate-700">
                  {shown.verification.tested ? `${shown.verification.matched?.toLocaleString("vi-VN")} / ${shown.verification.tested.toLocaleString("vi-VN")} dòng khớp (${((shown.verification.rate ?? 0) * 100).toFixed(2)}%)` : "Chưa có"}
                  {shown.verification.note ? ` — ${shown.verification.note}` : ""}
                </p>
              </div>
            </section>
            {shown.column_code === "BEGIN_PROD_DATE" && (
              <p className="rounded-lg border border-amber-300/50 p-3 text-xs text-amber-700">
                Phần dòng còn lại không khớp là mốc ngày nhập tay trong workbook (không có quy tắc công thức). Khi tạo phiên bản nền, các dòng đó được ghi thành OVERRIDE ("!") để giữ nguyên giá trị gốc.
              </p>
            )}
            {shown.cases && shown.cases.length > 0 && (
              <section>
                <h3 className="mb-1 text-xs font-bold uppercase text-slate-400">Ca chuẩn từ workbook ({shown.cases.filter((c) => c.ok).length}/{shown.cases.length} đạt)</h3>
                <CaseTable cases={shown.cases} type={type} />
              </section>
            )}
          </div>
        )}

        {data && data.versions.length > 0 && (
          <section className="mt-5">
            <h3 className="mb-1 text-xs font-bold uppercase text-slate-400">Lịch sử phiên bản</h3>
            <table className="w-full text-left text-xs">
              <tbody>
                {data.versions.map((v) => (
                  <tr key={v.id} className="border-b border-slate-50">
                    <td className="py-1.5 font-semibold">v{v.version}</td>
                    <td><span className={`pg-chip ${STATUS_TONE[v.status]}`}>{v.status}</span></td>
                    <td className="max-w-[300px] truncate font-mono text-slate-500" title={v.expression}>{v.expression}</td>
                    <td className="text-slate-500">{v.published_at ? `${v.published_by} · ${dateTimeVi(v.published_at)}` : `${v.created_by} · ${dateTimeVi(v.created_at)}`}</td>
                    <td className="text-right">
                      <button
                        onClick={async () => setOpenDef((await api.get<FormulaDef>(`/planning/formulas/${v.id}`)).data)}
                        className="mr-2 text-brand hover:underline"
                      >
                        Xem
                      </button>
                      {canManage && v.status === "DRAFT" && (
                        <button onClick={() => publish(v.id)} disabled={busy !== ""} className="rounded-full border border-slate-300 px-3 py-0.5 hover:bg-slate-100">Publish</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {openDef && <button onClick={() => setOpenDef(null)} className="mt-2 text-xs text-slate-500 underline">Quay lại bản đang hiệu lực</button>}
          </section>
        )}

        <section className="mt-6 border-t border-slate-100 pt-4">
          <h3 className="text-xs font-bold uppercase text-slate-400">Thử / soạn công thức</h3>
          <textarea value={expr} onChange={(e) => setExpr(e.target.value)} rows={3} spellCheck={false} className="mt-2 w-full rounded-lg border border-slate-200 p-2 font-mono text-xs" aria-label="Biểu thức công thức" />
          <textarea
            value={inputs}
            onChange={(e) => setInputs(e.target.value)}
            rows={2}
            spellCheck={false}
            className="mt-2 w-full rounded-lg border border-slate-200 p-2 font-mono text-xs"
            aria-label="Đầu vào thử (JSON)"
            placeholder='{"QUANTITY": 1110, "CAPACITY": 1200}'
          />
          <p className="text-[11px] text-slate-400">Đầu vào thử: {'{"QUANTITY": 1110, "CAPACITY": 1200}'} hoặc {'{"inputs": {...}, "prev": {"END_BEGIN_DATE": 46000, "TOTAL_DAY": 2}, "manual": 46001}'}. Ngày là số serial Excel.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button onClick={validate} disabled={busy !== ""} className="rounded-full border border-slate-300 px-4 py-1.5 text-xs hover:bg-slate-100">Validate</button>
            <button onClick={preview} disabled={busy !== ""} className="rounded-full border border-slate-300 px-4 py-1.5 text-xs hover:bg-slate-100">Tính thử</button>
            {canManage && (
              <button onClick={saveDraft} disabled={busy !== ""} className="rounded-full bg-brand px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-50">Lưu bản nháp mới</button>
            )}
          </div>
          {check && (
            <div className={`mt-3 rounded-lg border p-3 text-xs ${check.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`}>
              {check.ok ? (
                <p>{check.result !== undefined ? `Kết quả: ${JSON.stringify(check.result)}` : "Công thức hợp lệ (cú pháp, cột, hàm, không vòng phụ thuộc)."}</p>
              ) : (
                <ul className="list-inside list-disc">{(check.errors ?? [check.error]).map((m) => <li key={m}>{m}</li>)}</ul>
              )}
            </div>
          )}
        </section>
      </aside>
    </div>
  );
}

export default function ColumnConfig() {
  const { can } = useAuth();
  const [cols, setCols] = useState<PlanColumnCfg[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setCols((await api.get<PlanColumnCfg[]>("/planning/columns")).data);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => cols.filter((c) => !q || `${c.code} ${c.label} ${c.workbook_header}`.toLowerCase().includes(q.toLowerCase())), [cols, q]);
  const calc = cols.filter((c) => c.input_type === "CALCULATED").length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Cấu hình cột Planning</h1>
          <p className="text-xs text-slate-500">
            {cols.length} cột · {calc} cột tính theo công thức đã Publish · bấm một dòng để xem giải thích công thức, ca chuẩn từ workbook và lịch sử phiên bản.
          </p>
        </div>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm cột..." className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm" aria-label="Tìm cột" />
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full min-w-[820px] text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
              <th className="px-4 py-2.5">Planning column</th>
              <th>Input type</th>
              <th>List source</th>
              <th>Formula</th>
              <th className="pr-4">Sample result</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.code} onClick={() => setOpen(c.code)} className="cursor-pointer border-b border-slate-50 hover:bg-slate-50" data-testid={`col-${c.code}`}>
                <td className="px-4 py-2">
                  <span className="font-semibold text-slate-800">{c.code}</span>
                  <span className="block text-[11px] text-slate-400">{c.workbook_header}</span>
                </td>
                <td>
                  <span className={`pg-chip ${c.input_type === "CALCULATED" ? "pg-viol" : c.input_type === "LIST" ? "pg-known" : "pg-unk"}`}>{INPUT_LABEL[c.input_type]}</span>
                </td>
                <td className="text-slate-500">{c.list_source || "—"}</td>
                <td className="max-w-[380px] truncate font-mono text-xs text-slate-700" title={c.formula ?? ""}>
                  {c.formula ? `v${c.formula_version} · ${c.formula}` : c.has_draft ? <span className="text-amber-600">bản nháp chưa Publish</span> : "—"}
                </td>
                <td className="pr-4 text-slate-800">{c.sample === null ? "—" : show(c.sample, c.value_type)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && <Explain code={open} canManage={can("formula.manage")} onClose={() => setOpen(null)} onChanged={load} />}
    </div>
  );
}
