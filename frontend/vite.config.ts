import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";

const PRODUCTION_API_BASE_URL = "https://shira.tailfb111b.ts.net";
const FRONTEND_ORIGIN = "https://fastapi-5-4.vercel.app";
const isLocalApiBaseUrl = (url: string) => /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(url);

function normalizeUrl(url: string) {
  return url.trim().replace(/\/+$/, "");
}

function resolveApiBaseUrl(mode: string) {
  const env = loadEnv(mode, process.cwd(), "");
  const configuredUrl = normalizeUrl(env.VITE_API_BASE_URL ?? "");

  if (mode !== "production") {
    return configuredUrl;
  }

  // In production, the API must point to the real FastAPI backend, not the Vercel SPA origin.
  if (!configuredUrl || isLocalApiBaseUrl(configuredUrl) || configuredUrl === FRONTEND_ORIGIN) {
    return PRODUCTION_API_BASE_URL;
  }

  return configuredUrl;
}

export default defineConfig(({ mode }) => {
  const apiBaseUrl = resolveApiBaseUrl(mode);

  return {
    plugins: [react()],
    define: {
      "import.meta.env.VITE_API_BASE_URL": JSON.stringify(apiBaseUrl)
    },
    server: {
      port: 3000
    },
    preview: {
      port: 3000
    },
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url))
      }
    }
  };
});
