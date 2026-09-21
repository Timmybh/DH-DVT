import { CSSProperties } from "react";
import { RuntimeItem, RuntimeResponse } from "../../api/client";
import { DashActions, renderIndicator } from "./renderers";

interface Props {
  runtime: RuntimeResponse;
  actions: DashActions;
}

/** Dashboard theo Section: mỗi Section là một hàng chia cột theo preset (100 | 50/50 | 66/34 | 34/66 | 33/33/33 | 25×4); widget xếp chồng trong cột.
 *  Bố cục lưới cũ (chưa có Section) vẫn được vẽ theo grid_x/grid_y/width/height. */
export default function DashboardCanvas({ runtime, actions }: Props) {
  if (!runtime.layout) {
    return <p className="rounded-xl border border-slate-200 p-4 text-sm text-slate-500">{runtime.message ?? "Chưa có bố cục Dashboard nào được Publish."}</p>;
  }
  if (runtime.items.length === 0) {
    return <p className="rounded-xl border border-slate-200 p-4 text-sm text-slate-500">Bố cục "{runtime.layout.layout_name}" chưa có chỉ số nào hiển thị.</p>;
  }
  const sections = runtime.sections ?? [];
  if (sections.length > 0) {
    return (
      <div className="space-y-5" data-testid="dash-sections" data-layout={`${runtime.layout.layout_code}.v${runtime.layout.version}`}>
        {sections.map((sec) => {
          const mine = runtime.items.filter((i) => i.section_id === sec.id);
          if (mine.length === 0) return null;
          const style = { "--cols": sec.spans.map((s) => `${s}fr`).join(" ") } as CSSProperties;
          const byCol = (ci: number): RuntimeItem[] => mine.filter((i) => Math.min(i.column_no ?? 0, sec.spans.length - 1) === ci);
          return (
            <div key={sec.id} className="dash-section" style={style} data-testid={`dash-section-${sec.id}`} data-preset={sec.preset}>
              {sec.spans.map((_s, ci) => (
                <div key={ci} className="min-w-0 space-y-5">
                  {byCol(ci).map((it) => <div key={it.item_id ?? it.indicator.indicator_code} className="min-w-0">{renderIndicator(it, actions)}</div>)}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    );
  }
  return (
    <div className="dash-grid" data-testid="dash-grid" data-layout={`${runtime.layout.layout_code}.v${runtime.layout.version}`}>
      {runtime.items.map((it) => {
        const p = it.position;
        const style = { "--gc": `${p.x + 1} / span ${p.w}`, "--gr": `${p.y + 1} / span ${p.h}`, "--ord": p.order } as CSSProperties;
        return (
          <div key={it.item_id ?? it.indicator.indicator_code} className="dash-item min-w-0" style={style}>
            {renderIndicator(it, actions)}
          </div>
        );
      })}
    </div>
  );
}
