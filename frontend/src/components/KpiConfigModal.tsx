import { useState } from "react";
import { api, KpiConfigOut } from "../api/client";

interface KpiConfigModalProps {
  configs: KpiConfigOut[];
  onClose: () => void;
  onSaved: () => void;
}

export default function KpiConfigModal({ configs, onClose, onSaved }: KpiConfigModalProps) {
  const [rows, setRows] = useState(configs);
  const [saving, setSaving] = useState(false);

  function updateRow(id: number, field: keyof KpiConfigOut, value: unknown) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
  }

  async function saveAll() {
    setSaving(true);
    await Promise.all(
      rows.map((r) =>
        api.put(`/dashboard/kpi-config/${r.id}`, {
          label: r.label,
          unit: r.unit,
          target_value: r.target_value,
          warning_threshold_pct: r.warning_threshold_pct,
          gauge_slot: r.gauge_slot,
          display_order: r.display_order,
          is_active: r.is_active,
        }),
      ),
    );
    setSaving(false);
    onSaved();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-bold text-slate-900">Cấu hình KPI</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            ✕
          </button>
        </div>

        <div className="space-y-3">
          {rows.map((r) => (
            <div key={r.id} className="grid grid-cols-12 items-center gap-2 rounded-lg border border-slate-100 p-2">
              <input
                className="col-span-4 rounded border border-slate-200 px-2 py-1 text-sm"
                value={r.label}
                onChange={(e) => updateRow(r.id, "label", e.target.value)}
              />
              <input
                className="col-span-1 rounded border border-slate-200 px-2 py-1 text-sm"
                value={r.unit}
                onChange={(e) => updateRow(r.id, "unit", e.target.value)}
                placeholder="đv"
              />
              <input
                className="col-span-2 rounded border border-slate-200 px-2 py-1 text-sm"
                type="number"
                value={r.target_value ?? ""}
                onChange={(e) => updateRow(r.id, "target_value", e.target.value ? Number(e.target.value) : null)}
                placeholder="Mục tiêu"
              />
              <input
                className="col-span-2 rounded border border-slate-200 px-2 py-1 text-sm"
                type="number"
                value={r.gauge_slot ?? ""}
                onChange={(e) => updateRow(r.id, "gauge_slot", e.target.value ? Number(e.target.value) : null)}
                placeholder="Gauge #"
              />
              <label className="col-span-2 flex items-center gap-1 text-xs text-slate-600">
                <input
                  type="checkbox"
                  checked={r.is_active}
                  onChange={(e) => updateRow(r.id, "is_active", e.target.checked)}
                />
                Hoạt động
              </label>
            </div>
          ))}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">
            Hủy
          </button>
          <button
            onClick={saveAll}
            disabled={saving}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-60"
          >
            {saving ? "Đang lưu..." : "Lưu thay đổi"}
          </button>
        </div>
      </div>
    </div>
  );
}
