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
  if (/pure[ -]python|not yet (?:a )?durable/i.test(html)) {
    failures.push(`${relative}: obsolete runtime/durability claim`);
  }
  if (/data-demo|data-reveal|Live engine|Play update sequence/i.test(html)) {
    failures.push(`${relative}: obsolete simulated-engine or reveal markup`);
  }
  if (!/<html[^>]+lang=["'][^"']+["']/i.test(html)) failures.push(`${relative}: missing html lang`);
  if (!/<title>[^<]+<\/title>/i.test(html)) failures.push(`${relative}: missing title`);
  if ((html.match(/class="logo-rail"/g) ?? []).length !== 2) failures.push(`${relative}: header/footer must share the branded mark`);
  if (!html.includes("favicon.svg?v=paired-20261003") || !html.includes("apple-touch-icon.png")) failures.push(`${relative}: missing current favicon/touch branding`);
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
  if (html.includes("data-demo-canvas") && !/data-demo-status[^>]+aria-live=["']polite["']/i.test(html)) {
    failures.push(`${relative}: interactive demo missing polite live status`);
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
const home = await fs.readFile(path.join(dist, "index.html"), "utf8");
const walkthrough = await fs.readFile(path.join(dist, "playground", "index.html"), "utf8");
const mark = await fs.readFile(path.join(dist, "mark.svg"), "utf8");
const paths = [...mark.matchAll(/<path\b[^>]*\bd="([^"]+)"/g)].map(match => match[1]);
if (paths.length !== 2) failures.push("brand: expected paired-rail and matching-bar geometry");
for (const asset of ["favicon.svg", "logo.svg", "og.svg"]) {
  const svg = await fs.readFile(path.join(dist, asset), "utf8");
  if (!paths.every(geometry => svg.includes(`d="${geometry}"`))) failures.push(`${asset}: brand geometry diverges from mark.svg`);
}
if (!home.includes('data-theme="light"')) failures.push("home: expected ivory/teal default theme");
if (!home.includes("Verified native eight-vertex update and recovery trace")) failures.push("home: missing verified native trace");
if (!walkthrough.includes('data-verify="python"') || !walkthrough.includes("recovered.submit")) failures.push("walkthrough: missing executable reopen/retry verification");
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log(`Checked ${files.length} HTML pages, internal links, metadata, and the verified native walkthrough.`);
