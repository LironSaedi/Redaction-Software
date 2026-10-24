import { useEffect, useRef } from "react";

/** True when a key press should go to a form control (or an open dialog), not to shortcuts. */
export function isTypingTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  if (t.isContentEditable) return true;
  const tag = t.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const type = (t as HTMLInputElement).type;
    return !["checkbox", "radio", "button", "range"].includes(type);
  }
  return false;
}

export type HotkeyMap = Record<string, (e: KeyboardEvent) => void>;

/** Name of a key event in a HotkeyMap: "d", "?", "ArrowLeft", "shift+ArrowLeft", "mod+z", "mod+shift+z". */
export function hotkeyName(e: Pick<KeyboardEvent, "key" | "shiftKey" | "metaKey" | "ctrlKey">): string {
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (e.metaKey || e.ctrlKey) return `mod+${e.shiftKey ? "shift+" : ""}${key}`;
  return e.shiftKey && e.key.length > 1 ? `shift+${key}` : key;
}

/**
 * Window-level shortcuts. Keys are KeyboardEvent.key values ("ArrowLeft", "d", "+"), optionally prefixed with
 * "shift+" (named keys) or "mod+" (Ctrl on Windows / Linux, ⌘ on macOS). Ignored while typing in a field or while
 * a modal dialog is open. Unmapped Ctrl / ⌘ combinations are left to the browser.
 */
export function useHotkeys(map: HotkeyMap, enabled = true, opts: { capture?: boolean } = {}): void {
  const capture = !!opts.capture;
  const ref = useRef(map);
  ref.current = map;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      // sliders keep their own arrow / page keys (e.g. the video seek bar)
      if (e.target instanceof HTMLInputElement && e.target.type === "range" && /^(Arrow|Home|End|Page)/.test(e.key)) return;
      if (document.querySelector(".modal-backdrop")) return;
      const name = hotkeyName(e);
      if (name.startsWith("mod+")) {
        const fn = ref.current[name];
        if (fn) {
          e.preventDefault();
          fn(e);
        }
        return;
      }
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      const fn = ref.current[name] ?? ref.current[key];
      if (fn) fn(e);
    };
    // capture-phase maps run before the normal ones and can claim a key with preventDefault()
    window.addEventListener("keydown", onKey, capture);
    return () => window.removeEventListener("keydown", onKey, capture);
  }, [enabled, capture]);
}

/** Track whether a key (default Space) is held down, e.g. for temporary hand-tool panning. */
export function useKeyHeld(key: string, onChange: (held: boolean) => void, enabled = true): void {
  const cb = useRef(onChange);
  cb.current = onChange;
  useEffect(() => {
    if (!enabled) return;
    let held = false;
    const down = (e: KeyboardEvent) => {
      if (e.key !== key || e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e.target) || document.querySelector(".modal-backdrop")) return;
      const t = e.target as HTMLElement | null;
      // a focused button / checkbox keeps Space for itself
      if (t && t.closest("button, [role=button], [role=radio], [role=tab], a, input")) return;
      e.preventDefault();
      held = true;
      cb.current(true);
    };
    const up = (e: KeyboardEvent) => {
      if (e.key !== key || !held) return;
      held = false;
      cb.current(false);
    };
    const blur = () => {
      if (held) {
        held = false;
        cb.current(false);
      }
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, [key, enabled]);
}
