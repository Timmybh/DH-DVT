import { LayoutGrid } from "lucide-react";
import { CATEGORY_ICON, categoryVars, STATUS_LEGEND, STATUS_VARS } from "./tokens";

export default function CategoryFilter({ active, onToggle }: { active: Set<string>; onToggle: (c: string) => void }) {
  const cats = Object.keys(CATEGORY_ICON);
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => cats.forEach((c) => { if (active.has(c)) onToggle(c); })}
          className="inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-xs font-semibold text-white shadow-sm"
          style={{ background: "var(--rm-text)" }} data-testid="rm-cat-all"
        >
          <LayoutGrid size={14} />Tất cả danh mục
        </button>
        {cats.map((c) => {
          const Icon = CATEGORY_ICON[c];
          const v = categoryVars(c);
          const on = !active.has(c);
          return (
            <button key={c} onClick={() => onToggle(c)} className="inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-xs font-semibold transition" style={{ color: v.fg, background: v.bg, opacity: on ? 1 : 0.4 }} data-testid={`rm-cat-${c}`}>
              <Icon size={14} strokeWidth={2.25} />{c}
            </button>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-3 text-[11px]" style={{ color: "var(--rm-text-muted)" }}>
        {STATUS_LEGEND.map((s) => (
          <span key={s.status} className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: STATUS_VARS[s.status].fg }} />{s.label}</span>
        ))}
      </div>
    </div>
  );
}
