// @ts-check
import { defineConfig } from "astro/config";

// GitHub Pages project site: https://rockorama.github.io/angelo-tese
// Override with BASE_PATH / SITE_URL env vars (e.g. for a custom domain).
export default defineConfig({
  site: process.env.SITE_URL ?? "https://rockorama.github.io",
  base: process.env.BASE_PATH ?? "/angelo-tese",
  trailingSlash: "ignore",
  build: { format: "directory" },
});
