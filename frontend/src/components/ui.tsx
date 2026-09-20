/** The pieces every screen is made of. They only carry the system's classes (organic.css
 *  and app.css), so a screen describes what it is, never how it looks. */

import { Check, X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { urls } from "../api/client";
import type { DocumentSummary } from "../api/types";
import { t } from "../i18n";

/** Close on Escape and, with ``ref``, on a click outside it (``ignore``: the button that
 *  toggles it, which closes it by itself). */
export function useDismiss(
  active: boolean,
  close: () => void,
  ref?: React.RefObject<HTMLElement | null>,
  ignore?: React.RefObject<HTMLElement | null>,
): void {
  useEffect(() => {
    if (!active) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
      }
    };
    const onClick = (event: MouseEvent) => {
      const target = event.target as Node;
      if (ignore?.current?.contains(target)) return;
      if (ref?.current && !ref.current.contains(target)) close();
    };
    document.addEventListener("keydown", onKey, true);
    if (ref) document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (ref) document.removeEventListener("mousedown", onClick);
    };
  }, [active, close, ref, ignore]);
}

/** The two quotes: the dark one opens (the original), the terracota closes (the translation). */
export function Brand({
  size = 18,
  word = true,
  tag = false,
  onNight = false,
}: {
  size?: number;
  word?: boolean;
  tag?: boolean;
  onNight?: boolean;
}) {
  return (
    <span className={`brand ${onNight ? "on-night" : ""}`} style={{ fontSize: size }}>
      <BrandMark />
      {word ? <span className="brand-word">Polyglot</span> : null}
      {tag ? <span className="brand-tag">PDF</span> : null}
    </span>
  );
}

export function BrandMark({ style }: { style?: React.CSSProperties }) {
  return (
    <span className="brand-mark" aria-hidden="true" style={style}>
      <span className="open">“</span>
      <span className="close">”</span>
    </span>
  );
}

/** A book's cover image, or — when the file has none — nothing, so the drawn cover shows. */
export function CoverArt({ item, className }: { item: DocumentSummary; className?: string }) {
  const [state, setState] = useState<"loading" | "loaded" | "failed">("loading");
  if (state === "failed") return null;
  return (
    <img
      className={`${className ?? ""} ${state === "loaded" ? "loaded" : ""}`}
      src={urls.cover(item.id)}
      alt=""
      loading="lazy"
      draggable={false}
      onLoad={() => setState("loaded")}
      onError={() => setState("failed")}
    />
  );
}

/** The small cover used in lists and dialogs: always the same size. */
export function Spine({ item, className = "spine" }: { item: DocumentSummary; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <span className={className} aria-hidden="true" />;
  return (
    <img
      className={className}
      src={urls.cover(item.id)}
      alt=""
      loading="lazy"
      draggable={false}
      onError={() => setFailed(true)}
    />
  );
}

export function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange(value: boolean): void;
  label: string;
}) {
  return (
    <button
      type="button"
      className="switch"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
    >
      <i />
    </button>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  variant = "",
}: {
  value: T;
  options: { value: T; label: ReactNode; disabled?: boolean; title?: string }[];
  /** ``NoInfer``: a state setter passed here must not widen T to its own argument type. */
  onChange(value: NoInfer<T>): void;
  variant?: "" | "on-paper" | "sm" | "on-paper sm";
}) {
  return (
    <div className={`segmented ${variant}`}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          disabled={option.disabled}
          title={option.title}
          onClick={() => option.value !== value && onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Checkbox({
  checked,
  onChange,
  children,
}: {
  checked: boolean;
  onChange(value: boolean): void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className="checkbox"
      role="checkbox"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
    >
      <span className="box">{checked ? <Check size={12} strokeWidth={3.4} /> : null}</span>
      {children}
    </button>
  );
}

const MENU_GAP = 8;
const MENU_MARGIN = 12;

/** A menu that floats above the page, next to the button that opens it. It lives outside
 *  the screen's layers, so nothing (the next row of covers, a scrolling list) covers or
 *  clips it; it opens upwards when there is no room below. */
export function Menu({
  open,
  onClose,
  children,
  anchor,
  align = "right",
}: {
  open: boolean;
  onClose(): void;
  children: ReactNode;
  anchor: RefObject<HTMLElement | null>;
  align?: "left" | "right";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  const closing = useRef(onClose);
  useEffect(() => {
    closing.current = onClose;
  });
  useDismiss(open, onClose, ref, anchor);

  useLayoutEffect(() => {
    if (!open) {
      setPlace(null);
      return;
    }
    const measure = () => {
      const button = anchor.current?.getBoundingClientRect();
      const menu = ref.current;
      if (!button || !menu) return;
      const { offsetWidth: width, offsetHeight: height } = menu;
      const below = button.bottom + MENU_GAP;
      const top =
        below + height > window.innerHeight - MENU_MARGIN && button.top - MENU_GAP - height > MENU_MARGIN
          ? button.top - MENU_GAP - height
          : below;
      const start = align === "left" ? button.left : button.right - width;
      const left = Math.min(Math.max(MENU_MARGIN, start), window.innerWidth - width - MENU_MARGIN);
      setPlace({ top, left });
    };
    measure();
    // A page that moves under the menu would leave it pointing at nothing.
    const close = () => closing.current();
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [open, anchor, align]);

  if (!open) return null;
  return createPortal(
    <div
      className="menu"
      role="menu"
      ref={ref}
      style={place ? { top: place.top, left: place.left } : { visibility: "hidden" }}
    >
      {children}
    </div>,
    document.body,
  );
}

export function Dialog({
  onClose,
  children,
  wide = false,
  label,
}: {
  onClose(): void;
  children: ReactNode;
  wide?: boolean;
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useDismiss(true, onClose);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  const onScrim = useCallback(
    (event: React.MouseEvent) => {
      if (event.target === event.currentTarget) onClose();
    },
    [onClose],
  );
  return (
    <div className="scrim" onMouseDown={onScrim}>
      <div
        className={`dialog ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        ref={ref}
      >
        <span className="dialog-close">
          <CloseButton onClick={onClose} />
        </span>
        {children}
      </div>
    </div>
  );
}

export function Drawer({
  side = "right",
  onClose,
  children,
}: {
  side?: "left" | "right";
  onClose(): void;
  children: ReactNode;
}) {
  useDismiss(true, onClose);
  return (
    <>
      <div className="drawer-scrim" onMouseDown={onClose} />
      <aside className={`drawer ${side}`} role="dialog" aria-modal="true">
        {children}
      </aside>
    </>
  );
}

export function CloseButton({
  onClick,
  label,
  className = "",
}: {
  onClick(): void;
  label?: string;
  className?: string;
}) {
  return (
    <button type="button" className={`icon-btn ${className}`} aria-label={label ?? t("common.close")} onClick={onClick}>
      <X size={16} strokeWidth={2.5} />
    </button>
  );
}

export function Progress({
  value,
  tone = "normal",
  thin = false,
  onNight = false,
}: {
  value: number;
  tone?: "normal" | "done" | "live";
  thin?: boolean;
  onNight?: boolean;
}) {
  const width = `${Math.max(0, Math.min(1, value)) * 100}%`;
  const classes = ["progress", tone === "normal" ? "" : tone, thin ? "thin" : "", onNight ? "on-night" : ""];
  return (
    <div className={classes.join(" ")}>
      <i style={{ width }} />
    </div>
  );
}

export function Spinner({ large = false }: { large?: boolean }) {
  return <span className={`spinner ${large ? "lg" : ""}`} aria-hidden="true" />;
}

export function Thinking() {
  return (
    <span className="thinking" aria-label={t("common.writing")}>
      <i />
      <i />
      <i />
    </span>
  );
}

export function Key({ children }: { children: ReactNode }) {
  return <kbd className="key">{children}</kbd>;
}

/** Enter sends, Shift+Enter breaks the line. */
export function submitsOnEnter(run: () => void) {
  return (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      run();
    }
  };
}
