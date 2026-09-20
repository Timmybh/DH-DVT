import { useEffect, useState } from "react";
import { api, errorMessage } from "../../api/client";
import { ThemeTokens } from "../../theme/palette";
import { useTheme } from "../../theme/ThemeContext";

const STATUS_LABEL: Record<keyof ThemeTokens["status"], string> = { ok: "Tốt / đạt", warn: "Cảnh báo", bad: "Xấu / trễ", info: "Thông tin / sớm", neutral: "Trung tính / chưa có dữ liệu" };

function Color({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input type="color" value={value} onChange={(e) => onChange(e.target.value)} className="h-8 w-10 cursor-pointer rounded border border-slate-300 bg-transparent" aria-label={label} />
      <span className="font-mono text-xs text-slate-500">{value}</span>
      <span>{label}</span>
    </label>
  );
}

export default function Theme() {
  const { tokens, setTokens, version, reload } = useTheme();
  const [draft, setDraft] = useState<ThemeTokens>(tokens);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => setDraft(tokens), [tokens]);

  const preview = (t: ThemeTokens) => setDraft(t);
  const save = async () => {
    try {
      const r = await api.put<{ tokens: ThemeTokens; version: number }>("/theme", { tokens: draft });
      setTokens(r.data.tokens, r.data.version);
      setMsg({ ok: true, text: `Đã lưu giao diện (phiên bản ${r.data.version}). Áp dụng ngay cho mọi người dùng ở lần tải trang kế tiếp.` });
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };
  const reset = async () => {
    if (!window.confirm("Đặt lại toàn bộ màu về mặc định?")) return;
    try {
      const r = await api.post<{ tokens: ThemeTokens; version: number }>("/theme/reset");
      setTokens(r.data.tokens, r.data.version);
      setMsg({ ok: true, text: "Đã đặt lại về mặc định." });
    } catch (e) {
      setMsg({ ok: false, text: errorMessage(e) });
    }
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(tokens);

  return (
    <div className="space-y-5" data-testid="theme-admin">
      <div>
        <h1 className="text-xl font-bold text-slate-900">Giao diện (Theme)</h1>
        <p className="text-xs text-slate-500">
          Một nguồn màu duy nhất cho toàn hệ thống: màu thương hiệu (nút, tab), màu trạng thái (đồng hồ, biểu đồ tiến độ) và dải màu biểu đồ theo xí nghiệp. Mỗi người dùng tự chọn chế độ sáng / tối ở thanh trên cùng; chế độ đó lưu riêng trên trình duyệt của họ.
          Phiên bản hiện hành: {version || "mặc định"}.
        </p>
      </div>
      {msg && <p className={`rounded-lg border px-3 py-2 text-sm ${msg.ok ? "border-green-300/50 text-green-700" : "border-red-300/50 text-red-700"}`} role="status">{msg.text}</p>}

      <section className="rounded-2xl border border-slate-200 bg-white p-4">
        <h3 className="mb-3 text-xs font-bold uppercase text-slate-400">Màu thương hiệu</h3>
        <Color label="Màu chủ đạo" value={draft.brand} onChange={(v) => preview({ ...draft, brand: v })} />
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4">
        <h3 className="mb-3 text-xs font-bold uppercase text-slate-400">Màu trạng thái</h3>
        <div className="grid gap-3 md:grid-cols-2">
          {(Object.keys(STATUS_LABEL) as (keyof ThemeTokens["status"])[]).map((k) => (
            <Color key={k} label={STATUS_LABEL[k]} value={draft.status[k]} onChange={(v) => preview({ ...draft, status: { ...draft.status, [k]: v } })} />
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4">
        <h3 className="mb-3 text-xs font-bold uppercase text-slate-400">Dải màu biểu đồ / xí nghiệp (3–8 màu; XN1 = màu 1, XN2 = màu 2...)</h3>
        <div className="flex flex-wrap items-center gap-4">
          {draft.series.map((c, i) => (
            <Color key={i} label={`Màu ${i + 1}`} value={c} onChange={(v) => preview({ ...draft, series: draft.series.map((x, j) => (j === i ? v : x)) })} />
          ))}
          <button disabled={draft.series.length >= 8} onClick={() => preview({ ...draft, series: [...draft.series, "#94a3b8"] })} className="rounded-full border border-slate-300 px-3 py-1 text-xs disabled:opacity-40">+ Thêm màu</button>
          <button disabled={draft.series.length <= 3} onClick={() => preview({ ...draft, series: draft.series.slice(0, -1) })} className="rounded-full border border-slate-300 px-3 py-1 text-xs disabled:opacity-40">Bớt màu</button>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4" data-testid="theme-preview">
        <h3 className="mb-3 text-xs font-bold uppercase text-slate-400">Xem trước</h3>
        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-lg px-4 py-2 text-sm font-semibold text-white" style={{ background: draft.brand }}>Nút chính</span>
          {(Object.keys(STATUS_LABEL) as (keyof ThemeTokens["status"])[]).map((k) => <span key={k} className="rounded-full px-3 py-1 text-xs font-semibold text-white" style={{ background: draft.status[k] }}>{STATUS_LABEL[k]}</span>)}
          <span className="flex h-6 overflow-hidden rounded">{draft.series.map((c, i) => <span key={i} className="w-8" style={{ background: c }} />)}</span>
        </div>
      </section>

      <div className="flex gap-2">
        <button onClick={save} disabled={!dirty} className="rounded-full bg-brand px-5 py-2 text-sm font-semibold text-white disabled:opacity-40" data-testid="theme-save">Lưu</button>
        <button onClick={() => setDraft(tokens)} disabled={!dirty} className="rounded-full border border-slate-300 px-5 py-2 text-sm disabled:opacity-40">Hoàn tác thay đổi</button>
        <button onClick={reset} className="rounded-full border border-slate-300 px-5 py-2 text-sm">Đặt lại mặc định</button>
        <button onClick={reload} className="ml-auto rounded-full border border-slate-300 px-5 py-2 text-sm">Tải lại từ máy chủ</button>
      </div>
    </div>
  );
}
