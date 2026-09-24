import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const basePath = "/axiom/";
const failures = [];

async function htmlFiles(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await htmlFiles(absolute)));
    else if (entry.name.endsWith(".html")) files.push(absolute);
  }
  return files;
}

function targetFile(href, source) {
  const sourceUrl = `${basePath}${path.relative(dist, source).replaceAll(path.sep, "/")}`;
  const resolved = new URL(href, `https://axiom.invalid${sourceUrl}`);
  if (resolved.origin !== "https://axiom.invalid") return null;
  if (!resolved.pathname.startsWith(basePath)) return "outside-base";
  const relative = resolved.pathname.slice(basePath.length);
  if (!relative) return path.join(dist, "index.html");
  if (resolved.pathname.endsWith("/")) return path.join(dist, relative, "index.html");
  return path.join(dist, relative);
}

const files = await htmlFiles(dist);
if (files.length === 0) failures.push("site/dist contains no HTML files; run npm run build first");

for (const file of files) {
  const html = await fs.readFile(file, "utf8");
  const relative = path.relative(dist, file);
  if (!/<html[^>]+lang=["'][^"']+["']/i.test(html)) failures.push(`${relative}: missing html lang`);
  if (!/<title>[^<]+<\/title>/i.test(html)) failures.push(`${relative}: missing title`);
  if (!/<meta[^>]+name=["']description["'][^>]+content=["'][^"']+/i.test(html)) failures.push(`${relative}: missing description`);
  if ((html.match(/<h1\b/gi) ?? []).length !== 1) failures.push(`${relative}: expected exactly one h1`);
  if (html.includes('class="docs-sidebar"')) {
    const sidebar = html.match(/<aside\b[^>]*class=["']docs-sidebar["'][\s\S]*?<\/aside>/i)?.[0] ?? "";
    const currentRoutes = sidebar.match(/<a\b[^>]*aria-current=["']page["'][^>]*>/gi) ?? [];
    if (currentRoutes.length !== 1) failures.push(`${relative}: expected exactly one current documentation route`);
  }
  if (html.includes(`${basePath}/`)) failures.push(`${relative}: duplicate slash in site-base URL`);
  for (const image of html.matchAll(/<img\b([^>]*)>/gi)) {
    if (!/\balt=["'][^"']*["']/i.test(image[1])) failures.push(`${relative}: image missing alt text`);
  }
  for (const canvas of html.matchAll(/<canvas\b([^>]*)>/gi)) {
    if (!/\baria-label=["'][^"']+["']/i.test(canvas[1])) failures.push(`${relative}: canvas missing aria-label`);
    if (!/\btabindex=["']0["']/i.test(canvas[1])) failures.push(`${relative}: interactive canvas missing tabindex=0`);
  }
  if (/github\.com\/sachncs\/axiom\/(?:blob|tree)\/master\/(?:README|docs|CHANGELOG)/i.test(html)) {
    failures.push(`${relative}: core documentation redirects to GitHub`);
  }
  for (const match of html.matchAll(/\bhref=["']([^"']+)["']/gi)) {
    const href = match[1];
    if (href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:")) continue;
    const destination = targetFile(href, file);
    if (!destination || destination === "outside-base") continue;
    try {
      await fs.access(destination);
    } catch {
      failures.push(`${relative}: broken internal link ${href}`);
    }
  }
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log(`Checked ${files.length} HTML pages, internal links, metadata, and accessible graph canvases.`);
