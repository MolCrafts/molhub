import { createRequire } from "node:module";
import path from "node:path";
import { defineConfig } from "@rsbuild/core";
import { pluginReact } from "@rsbuild/plugin-react";
import { pluginTailwindcss } from "@rsbuild/plugin-tailwindcss";
import { tanstackStart } from "@tanstack/react-start/plugin/rsbuild";

const repositoryRoot = import.meta.dirname;
const vegaCanvasBrowser = createRequire(import.meta.url)
  .resolve("vega-canvas")
  .replace(/\.node\.js$/, ".browser.js");
const publicApiUrl = process.env.PUBLIC_MOLHUB_API_URL ?? "http://localhost:8787";
const publicRegistryRevision = process.env.PUBLIC_MOLHUB_REGISTRY_REVISION ?? "";

export default defineConfig({
  root: repositoryRoot,
  plugins: [
    pluginTailwindcss(),
    pluginReact(),
    tanstackStart({
      srcDirectory: "app/src",
      prerender: {
        enabled: true,
        crawlLinks: true,
        // Query variants share one output pathname; rendering them concurrently corrupts HTML.
        filter: (page) => !page.path.includes("?"),
        failOnError: true,
      },
    }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(repositoryRoot, "app/src"),
      "@brand": path.resolve(repositoryRoot, "../../.github/assets"),
      // The deploy artifact is a static browser app. Use Vega's DOM Canvas
      // adapter during prerender compilation too; node-canvas is never needed.
      "vega-canvas": vegaCanvasBrowser,
    },
  },
  source: {
    define: {
      "process.env.PUBLIC_MOLHUB_API_URL": JSON.stringify(publicApiUrl),
      "process.env.PUBLIC_MOLHUB_REGISTRY_REVISION": JSON.stringify(publicRegistryRevision),
    },
  },
  output: {
    assetPrefix: "/molhub/",
    distPath: {
      root: path.resolve(repositoryRoot, "dist"),
    },
  },
  server: {
    base: "/molhub",
    port: 4173,
  },
});
