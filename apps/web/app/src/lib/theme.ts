export type Theme = "light" | "dark";

const STORAGE_KEY = "molhub-theme";

export function currentTheme(): Theme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function preferredTheme(): Theme {
  if (typeof window === "undefined") return "light";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Storage is an enhancement. A blocked store must not block rendering.
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(theme: Theme): Theme {
  if (typeof document === "undefined") return theme;
  document.documentElement.classList.toggle("dark", theme === "dark");
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // The class already changed; persistence failure is non-fatal.
  }
  return theme;
}

export function toggleTheme(): Theme {
  return applyTheme(currentTheme() === "dark" ? "light" : "dark");
}

/** Runs before hydration to keep the first paint in the preferred theme. */
export const THEME_BOOTSTRAP = `(()=>{try{const s=localStorage.getItem('${STORAGE_KEY}');const d=s?s==='dark':matchMedia('(prefers-color-scheme: dark)').matches;document.documentElement.classList.toggle('dark',d)}catch{}})()`;
