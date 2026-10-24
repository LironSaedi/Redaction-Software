import { useEffect, useRef, useState } from "react";

// One tooltip for the whole app. Any element with `data-tip="…"` gets it on hover (after a short delay) and on
// keyboard focus. It is positioned in the viewport, so scrolling panels never clip it. Optional
// `data-tip-side="right" | "bottom"`. Tips are UI text only — never put detected values in them.

interface Tip {
  text: string;
  x: number;
  y: number;
  side: "top" | "bottom" | "right";
}

const DELAY = 380;

function place(el: Element): Tip | null {
  const text = el.getAttribute("data-tip");
  if (!text) return null;
  const r = el.getBoundingClientRect();
  const want = el.getAttribute("data-tip-side");
  if (want === "right") return { text, x: r.right + 8, y: r.top + r.height / 2, side: "right" };
  const side = want === "bottom" || r.top < 44 ? "bottom" : "top";
  return { text, x: r.left + r.width / 2, y: side === "top" ? r.top - 6 : r.bottom + 6, side };
}

export function TooltipLayer() {
  const [tip, setTip] = useState<Tip | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const current = useRef<Element | null>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [shift, setShift] = useState(0);

  useEffect(() => {
    const clear = () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
      if (current.current) current.current.removeAttribute("aria-describedby");
      current.current = null;
      setTip(null);
    };
    const show = (el: Element, delay: number) => {
      if (current.current === el) return;
      clear();
      current.current = el;
      timer.current = setTimeout(() => {
        if (!el.isConnected) return;
        const t = place(el);
        if (t) {
          el.setAttribute("aria-describedby", "app-tooltip");
          setShift(0);
          setTip(t);
        }
      }, delay);
    };
    const over = (e: Event) => {
      const el = (e.target as Element | null)?.closest?.("[data-tip]");
      if (el) show(el, DELAY);
      else if (current.current) clear();
    };
    const focus = (e: Event) => {
      const el = (e.target as Element | null)?.closest?.("[data-tip]");
      if (el && (el as HTMLElement).matches(":focus-visible")) show(el, 120);
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && clear();
    document.addEventListener("pointerover", over, true);
    document.addEventListener("pointerdown", clear, true);
    document.addEventListener("focusin", focus, true);
    document.addEventListener("focusout", clear, true);
    document.addEventListener("scroll", clear, true);
    document.addEventListener("keydown", key, true);
    window.addEventListener("blur", clear);
    return () => {
      clear();
      document.removeEventListener("pointerover", over, true);
      document.removeEventListener("pointerdown", clear, true);
      document.removeEventListener("focusin", focus, true);
      document.removeEventListener("focusout", clear, true);
      document.removeEventListener("scroll", clear, true);
      document.removeEventListener("keydown", key, true);
      window.removeEventListener("blur", clear);
    };
  }, []);

  // keep it inside the viewport horizontally
  useEffect(() => {
    const el = tipRef.current;
    if (!el || !tip) return;
    const r = el.getBoundingClientRect();
    const pad = 8;
    if (r.right > window.innerWidth - pad) setShift(window.innerWidth - pad - r.right);
    else if (r.left < pad) setShift(pad - r.left);
  }, [tip]);

  if (!tip) return null;
  return (
    <div
      ref={tipRef}
      id="app-tooltip"
      role="tooltip"
      className={`app-tooltip side-${tip.side}`}
      style={{ left: tip.x + shift, top: tip.y }}
    >
      {tip.text}
    </div>
  );
}
