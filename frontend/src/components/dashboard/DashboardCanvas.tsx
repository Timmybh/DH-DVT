import { CSSProperties } from "react";
import { RuntimeResponse } from "../../api/client";
import { DashActions, renderIndicator } from "./renderers";

interface Props {
  runtime: RuntimeResponse;
  actions: DashActions;
}

/** Canvas 12 cột: mỗi ô đặt theo grid_x/grid_y/width/height; màn hình hẹp xếp chồng theo order_no. */
export default function DashboardCanvas({ runtime, actions }: Props) {
  if (!runtime.layout) {
    return <p className="rounded-xl border border-slate-200 p-4 text-sm text-slate-500">{runtime.message ?? "Chưa có bố cục Dashboard nào được Publish."}</p>;
  }
  if (runtime.items.length === 0) {
    return <p className="rounded-xl border border-slate-200 p-4 text-sm text-slate-500">Bố cục "{runtime.layout.layout_name}" chưa có chỉ số nào hiển thị.</p>;
  }
  return (
    <div className="dash-grid" data-testid="dash-grid" data-layout={`${runtime.layout.layout_code}.v${runtime.layout.version}`}>
      {runtime.items.map((it) => {
        const p = it.position;
        const style = { "--gc": `${p.x + 1} / span ${p.w}`, "--gr": `${p.y + 1} / span ${p.h}`, "--ord": p.order } as CSSProperties;
        return (
          <div key={it.indicator.indicator_code} className="dash-item min-w-0" style={style}>
            {renderIndicator(it, actions)}
          </div>
        );
      })}
    </div>
  );
}
