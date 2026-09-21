import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import type { Col } from "./planColumns";

/** Chọn cột hiển thị: các cột đánh dấu `hidden` (VD SO Number) mặc định ẩn, người dùng bật qua "Cột"; lựa chọn nhớ theo từng lưới (localStorage). */
export function useColumnChooser<T>(storageKey: string, all: Col<T>[]): { cols: Col<T>[]; node: ReactNode } {
  const [shown, setShown] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(storageKey) ?? "[]");
    } catch {
      return [];
    }
  });
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const optional = useMemo(() => all.filter((c) => c.hidden), [all]);
  const cols = useMemo(() => all.filter((c) => !c.hidden || shown.includes(c.key)), [all, shown]);

  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", off);
    return () => document.removeEventListener("mousedown", off);
  }, [open]);

  const toggle = (key: string) =>
    setShown((cur) => {
      const next = cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key];
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        /* bỏ qua lỗi lưu cục bộ */
      }
      return next;
    });

  const node = optional.length ? (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-haspopup="true" aria-expanded={open} className="rounded-md border border-slate-300 px-2 py-1 text-xs" data-testid="col-chooser">
        Cột{shown.length ? ` (+${shown.length})` : ""} ▾
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 min-w-48 rounded-xl border border-slate-200 bg-white p-2 text-xs shadow-xl" role="menu">
          <p className="mb-1 px-1 font-bold uppercase text-slate-400">Cột bổ sung</p>
          {optional.map((c) => (
            <label key={c.key} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-slate-700 hover:bg-slate-100">
              <input type="checkbox" checked={shown.includes(c.key)} onChange={() => toggle(c.key)} data-testid={`col-toggle-${c.key}`} /> {c.label}
            </label>
          ))}
        </div>
      )}
    </div>
  ) : null;
  return { cols, node };
}
