import { PointerEvent as ReactPointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

const MIN_W = 44;

/** Độ rộng cột kéo giãn được, nhớ theo từng lưới (localStorage). `defaults` là độ rộng mặc định của từng cột. */
export function useColumnWidths(storageKey: string, defaults: { key: string; w: number }[]) {
  const [widths, setWidths] = useState<Record<string, number>>(() => {
    try {
      return JSON.parse(localStorage.getItem(storageKey) ?? "{}");
    } catch {
      return {};
    }
  });
  const drag = useRef<{ key: string; startX: number; startW: number } | null>(null);

  const widthOf = useCallback((key: string): number => widths[key] ?? defaults.find((d) => d.key === key)?.w ?? 100, [widths, defaults]);

  useEffect(() => {
    const move = (e: PointerEvent) => {
      const d = drag.current;
      if (!d) return;
      setWidths((cur) => ({ ...cur, [d.key]: Math.max(MIN_W, Math.round(d.startW + e.clientX - d.startX)) }));
    };
    const up = () => {
      if (!drag.current) return;
      drag.current = null;
      document.body.style.cursor = "";
      setWidths((cur) => {
        try {
          localStorage.setItem(storageKey, JSON.stringify(cur));
        } catch {
          /* bỏ qua lỗi lưu cục bộ */
        }
        return cur;
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [storageKey]);

  /** Gắn vào tay nắm ở mép phải tiêu đề cột. */
  const startResize = useCallback(
    (key: string, e: ReactPointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      drag.current = { key, startX: e.clientX, startW: widthOf(key) };
      document.body.style.cursor = "col-resize";
    },
    [widthOf],
  );

  const reset = useCallback(() => {
    setWidths({});
    try {
      localStorage.removeItem(storageKey);
    } catch {
      /* ignore */
    }
  }, [storageKey]);

  return useMemo(() => ({ widthOf, startResize, reset, customized: Object.keys(widths).length > 0 }), [widthOf, startResize, reset, widths]);
}
