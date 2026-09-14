import { fileURLToPath } from "node:url";
import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://sachncs.github.io",
  base: "/axiom/",
  trailingSlash: "never",
  build: {
    inlineStylesheets: "auto",
  },
  output: "static",
  vite: {
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
  },
});