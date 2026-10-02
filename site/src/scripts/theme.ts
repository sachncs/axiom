export function initTheme(): void {
  if (document.documentElement.dataset.themeInit) return;
  document.documentElement.dataset.themeInit = "1";
  const key = "axiom:theme";
  const toggle = document.querySelector<HTMLButtonElement>("[data-theme-toggle]");

  let stored: string | null = null;
  try { stored = localStorage.getItem(key); } catch { /* Theme still works without storage access. */ }
  const initial = stored === "light" || stored === "dark" ? stored : "light";
  document.documentElement.dataset.theme = initial;
  toggle?.setAttribute("aria-pressed", String(initial === "light"));

  toggle?.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    toggle.setAttribute("aria-pressed", String(next === "light"));
    try { localStorage.setItem(key, next); } catch { /* Keep the selection for this page. */ }
  });
}
