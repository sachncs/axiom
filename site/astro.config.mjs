import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://sachncs.github.io",
  base: "/axiom/",
  trailingSlash: "always",
  build: {
    inlineStylesheets: "auto",
  },
  output: "static",
});
