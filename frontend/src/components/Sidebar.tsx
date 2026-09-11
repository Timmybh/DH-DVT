import { IndicatorOut } from "../api/client";

interface SidebarProps {
  indicators: IndicatorOut[];
  onSelect: (indicator: IndicatorOut) => void;
  selectedKey: string | null;
}

export default function Sidebar({ indicators, onSelect, selectedKey }: SidebarProps) {
  return (
    <aside className="w-full shrink-0 space-y-3 lg:w-64">
      {indicators.map((ind) => {
        const isGreen = ind.status === "GREEN";
        const isSelected = ind.indicator_key === selectedKey;
        return (
          <button
            key={ind.indicator_key}
            onClick={() => onSelect(ind)}
            className={`w-full rounded-xl border-2 p-4 text-left transition ${
              isGreen ? "border-green-200 bg-green-50" : "border-red-200 bg-red-50"
            } ${isSelected ? "ring-2 ring-brand" : ""}`}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-700">{ind.label}</span>
              <span className={`h-3 w-3 rounded-full ${isGreen ? "bg-green-500" : "bg-red-500"}`} />
            </div>
            <p className="mt-1 text-2xl font-bold text-slate-900">
              {ind.value ?? "-"}
              {ind.value !== null && "%"}
            </p>
            <p className="mt-0.5 text-xs text-slate-500">Ngưỡng: {ind.threshold ?? "-"}%</p>
          </button>
        );
      })}
    </aside>
  );
}
