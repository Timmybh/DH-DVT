import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { dateTimeVi } from "../../lib/format";

interface Row {
  id: number;
  at: string;
  username: string;
  action: string;
  object_type: string;
  object_id: string;
  result: string;
  trace_id: string;
  detail: string;
}

const PAGE = 100;

export default function Audit() {
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [actions, setActions] = useState<string[]>([]);
  const [action, setAction] = useState("");
  const [username, setUsername] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/admin/audit", { params: { action: action || undefined, username: username || undefined, limit: PAGE, offset } });
      setRows(r.data.rows);
      setTotal(r.data.total);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [action, username, offset]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    api.get<string[]>("/admin/audit/actions").then((r) => setActions(r.data)).catch(() => undefined);
  }, []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Audit log</h1>
        <p className="text-sm text-slate-500">Đăng nhập, phân quyền, cấu hình SSO, đồng bộ và các thao tác quản trị · {total.toLocaleString("vi-VN")} bản ghi</p>
      </div>
      <div className="flex flex-wrap gap-3">
        <select value={action} onChange={(e) => { setOffset(0); setAction(e.target.value); }} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm">
          <option value="">Tất cả hành động</option>
          {actions.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <input value={username} onChange={(e) => { setOffset(0); setUsername(e.target.value); }} placeholder="Lọc theo tài khoản" className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm" />
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs uppercase text-slate-400">
              <th className="px-4 py-3">Thời gian</th><th>Tài khoản</th><th>Hành động</th><th>Đối tượng</th><th>Kết quả</th><th>Chi tiết</th><th className="px-4">Trace</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-slate-50 align-top">
                <td className="px-4 py-2 text-xs">{dateTimeVi(r.at)}</td>
                <td className="text-xs font-medium">{r.username || "—"}</td>
                <td className="font-mono text-xs">{r.action}</td>
                <td className="text-xs">{r.object_type} {r.object_id}</td>
                <td>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${r.result === "OK" ? "bg-green-100 text-green-700" : r.result === "FAILED" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"}`}>{r.result}</span>
                </td>
                <td className="max-w-sm break-words text-xs text-slate-500">{r.detail}</td>
                <td className="px-4 font-mono text-xs text-slate-400">{r.trace_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between text-sm text-slate-500">
        <span>{total ? `${offset + 1}–${Math.min(offset + PAGE, total)} / ${total}` : "Không có bản ghi"}</span>
        <div className="flex gap-2">
          <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="rounded-lg border border-slate-200 bg-white px-3 py-1 disabled:opacity-40">Trước</button>
          <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)} className="rounded-lg border border-slate-200 bg-white px-3 py-1 disabled:opacity-40">Sau</button>
        </div>
      </div>
    </div>
  );
}
