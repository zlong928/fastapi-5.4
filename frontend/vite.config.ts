import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";

const LOCAL_API_BASE_URL = "http://localhost:8000";
const PRODUCTION_API_BASE_URL = "https://shira.tailfb111b.ts.net";

function normalizeUrl(url: string) {
  return url.trim().replace(/\/+$/, "");
}

function isLocalApiBaseUrl(url: string) {
  return /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(url);
}

function resolveApiBaseUrl(mode: string) {
  const env = loadEnv(mode, process.cwd(), "");
  const configuredUrl = normalizeUrl(env.VITE_API_BASE_URL ?? "");

  if (mode === "production" && (!configuredUrl || isLocalApiBaseUrl(configuredUrl))) {
    return PRODUCTION_API_BASE_URL;
  }

  if (configuredUrl) {
    return configuredUrl;
  }

  return LOCAL_API_BASE_URL;
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
