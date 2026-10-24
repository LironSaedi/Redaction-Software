// Light / dark theme. Only this UI preference is kept in localStorage — never case data.
export type Theme = "light" | "dark";
const KEY = "obscura.theme";

export function loadTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function applyTheme(t: Theme): void {
  document.documentElement.dataset.theme = t;
  document.documentElement.style.colorScheme = t;
}

export function saveTheme(t: Theme): void {
  applyTheme(t);
  try {
    localStorage.setItem(KEY, t);
  } catch {
    /* ignore */
  }
}
