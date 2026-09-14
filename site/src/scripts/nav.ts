export function initNav(): void {
  if (document.documentElement.dataset.navInit) return;
  document.documentElement.dataset.navInit = "1";
  const header = document.querySelector(".nav");
  const burger = document.querySelector<HTMLButtonElement>("[data-nav-burger]");
  const mobile = document.querySelector<HTMLElement>("[data-nav-mobile]");

  const onScroll = () => {
    header?.classList.toggle("is-scrolled", window.scrollY > 12);
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  const close = () => {
    mobile?.classList.remove("is-open");
    burger?.setAttribute("aria-expanded", "false");
    burger?.setAttribute("aria-label", "Open menu");
  };

  burger?.addEventListener("click", () => {
    const open = mobile?.classList.toggle("is-open");
    burger.setAttribute("aria-expanded", String(open));
    burger.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  });

  mobile?.querySelectorAll("a").forEach((a) => a.addEventListener("click", close));
  window.addEventListener("resize", close);
}

document.addEventListener("astro:page-load", initNav);
if (document.readyState !== "loading") initNav();