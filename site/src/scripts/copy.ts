function initCopyCore(): void {
  const blocks = document.querySelectorAll<HTMLElement>("[data-copy]");
  if (!blocks.length) return;

  const done = new WeakSet<HTMLElement>();

  blocks.forEach((block) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy-btn";
    btn.setAttribute("data-copy-btn", "");
    btn.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg><span>Copy</span>';
    btn.addEventListener("click", async () => {
      const text = block.dataset.copy ?? block.textContent ?? "";
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        btn.querySelector("span")!.textContent = "Copy unavailable";
        window.setTimeout(() => {
          btn.querySelector("span")!.textContent = "Copy";
        }, 1600);
        return;
      }
      btn.classList.add("ok");
      btn.querySelector("span")!.textContent = "Copied";
      if (!done.has(block)) {
        done.add(block);
      }
      window.setTimeout(() => {
        btn.classList.remove("ok");
        btn.querySelector("span")!.textContent = "Copy";
      }, 1600);
    });
    block.appendChild(btn);
  });
}

function initCopy(): void {
  if (document.documentElement.dataset.copyInit) return;
  document.documentElement.dataset.copyInit = "1";
  initCopyCore();
}

document.addEventListener("astro:page-load", initCopy);
if (document.readyState !== "loading") initCopy();
