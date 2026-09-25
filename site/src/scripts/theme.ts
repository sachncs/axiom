export function initTheme(): void {
  if (document.documentElement.dataset.themeInit) return;
  document.documentElement.dataset.themeInit = "1";
  const key = "axiom:theme";
  const toggle = document.querySelector<HTMLButtonElement>("[data-theme-toggle]");

  const stored = localStorage.getItem(key);
  const initial = stored === "light" || stored === "dark" ? stored : "dark";
  document.documentElement.dataset.theme = initial;
  toggle?.setAttribute("aria-pressed", String(initial === "light"));

  toggle?.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    toggle.setAttribute("aria-pressed", String(next === "light"));
    localStorage.setItem(key, next);
  });
}
