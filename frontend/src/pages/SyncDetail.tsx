import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, errorMessage, SyncRun, SyncRunDetail } from "../api/client";
import Section, { StatusBadge } from "../components/Section";
import { useAuth } from "../context/AuthContext";
import { dateTimeVi, duration, num, SOURCE_LABEL } from "../lib/format";

const KIND_LABEL: Record<string, string> = { UNMATCHED: "Chưa khớp", AMBIGUOUS: "Mơ hồ", ERROR: "Lỗi kỹ thuật", INFO: "Thông tin" };

export default function SyncDetail() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const [run, setRun] = useState<SyncRunDetail | null>(null);
  const [kind, setKind] = useState("");
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);

  const load = useCallback(async () => {
    try {
      setRun((await api.get<SyncRunDetail>(`/sync/runs/${runId}`, { params: { kind: kind || undefined } })).data);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [runId, kind]);

  useEffect(() => {
    load();
  }, [load]);

  async function retry() {
    if (!run) return;
    setRetrying(true);
    try {
      const res = await api.post<SyncRun>(`/sync/runs/${run.id}/retry`);
      navigate(`/sync/${res.data.id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setRetrying(false);
    }
  }

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!run) return <p className="text-sm text-slate-500">Đang tải...</p>;

  const stats = [
    ["Tổng bản ghi", run.total_records],
    ["Khớp", run.matched],
    ["Chưa khớp", run.unmatched],
    ["Mơ hồ", run.ambiguous],
    ["Cập nhật", run.updated_rows],
  ] as const;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/sync" className="text-xs text-brand hover:underline">← Sync Log</Link>
          <h1 className="mt-1 flex items-center gap-3 text-xl font-bold text-slate-900">
            <span className="font-mono">{run.run_code}</span> <StatusBadge status={run.status} />
          </h1>
          <p className="text-xs text-slate-500">
            {SOURCE_LABEL[run.source] ?? run.source} · {run.trigger_type} · {run.triggered_by || "hệ thống"} · {dateTimeVi(run.started_at)} · {duration(run.duration_ms)} · Trace ID{" "}
            <span className="font-mono">{run.trace_id}</span>
            {run.retry_of ? ` · retry của run #${run.retry_of}` : ""}
          </p>
        </div>
        {can("sync.retry") && run.source === "EGMF_REVENUE" && (
          <button onClick={retry} disabled={retrying} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60">
            {retrying ? "Đang chạy lại..." : "Retry (tạo Sync Run mới)"}
          </button>
        )}
      </div>

      {run.error_message && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{run.error_message}</div>}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-xs text-slate-500">{label}</p>
            <p className="text-2xl font-bold text-slate-900">{num(value)}</p>
          </div>
        ))}
      </div>

      {run.summary.objects && (
        <Section title="Theo đối tượng nguồn" subtitle={run.summary.target ?? run.summary.filename}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
                <th className="py-2">Đối tượng</th>
                <th className="text-right">Đọc</th>
                <th className="text-right">Khớp</th>
                <th className="text-right">Chưa khớp</th>
                <th className="text-right">Bản cũ bị thay thế</th>
              </tr>
            </thead>
            <tbody>
              {run.summary.objects.map((o) => (
                <tr key={o.name} className="border-b border-slate-50">
                  <td className="py-2 font-mono text-xs">{o.name}</td>
                  <td className="text-right">{num(o.read)}</td>
                  <td className="text-right">{num(o.matched)}</td>
                  <td className={`text-right ${o.unmatched ? "font-semibold text-amber-600" : ""}`}>{num(o.unmatched)}</td>
                  <td className="text-right text-slate-400">{o.superseded !== undefined ? num(o.superseded) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      <Section
        title="Bản ghi cần chú ý"
        right={
          <select value={kind} onChange={(e) => setKind(e.target.value)} className="rounded-lg border border-slate-200 px-2 py-1 text-sm">
            <option value="">Tất cả ({Object.values(run.item_counts).reduce((a, b) => a + b, 0)})</option>
            {Object.entries(run.item_counts).map(([k, n]) => (
              <option key={k} value={k}>{KIND_LABEL[k] ?? k} ({n})</option>
            ))}
          </select>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
                <th className="py-2">Loại</th>
                <th>Đối tượng</th>
                <th>Khóa nguồn</th>
                <th>Nội dung</th>
              </tr>
            </thead>
            <tbody>
              {run.items.map((i) => (
                <tr key={i.id} className="border-b border-slate-50 align-top">
                  <td className="py-2 text-xs font-semibold text-amber-700">{KIND_LABEL[i.kind] ?? i.kind}</td>
                  <td className="font-mono text-xs">{i.source_object}</td>
                  <td className="font-mono text-xs">{i.source_key}</td>
                  <td className="break-words text-xs text-slate-600">{i.message}</td>
                </tr>
              ))}
              {run.items.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-6 text-center text-slate-400">Không có bản ghi nào cần chú ý.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
