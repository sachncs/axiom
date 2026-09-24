export function initReveal(): void {
  if (document.documentElement.dataset.revealInit) return;
  document.documentElement.dataset.revealInit = "1";
  const targets = document.querySelectorAll("[data-reveal]");
  if (!targets.length) return;

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) {
    targets.forEach((el) => el.classList.add("in-view"));
    return;
  }

  const io = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
          io.unobserve(entry.target);
        }
      }
    },
    { threshold: 0.12, rootMargin: "0px 0px -6% 0px" },
  );

  targets.forEach((el) => io.observe(el));
}

document.addEventListener("astro:page-load", initReveal);
if (document.readyState !== "loading") initReveal();