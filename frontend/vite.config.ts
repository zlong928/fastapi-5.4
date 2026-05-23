import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";

const isLocalApiBaseUrl = (url: string) => /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(url);

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiBaseUrl = env.VITE_API_BASE_URL;

  if (mode === "production" && !apiBaseUrl) {
    throw new Error("Missing VITE_API_BASE_URL in production.");
  }

  if (mode === "production" && apiBaseUrl && isLocalApiBaseUrl(apiBaseUrl)) {
    throw new Error("VITE_API_BASE_URL must not point to localhost in production.");
  }

  return {
    plugins: [react()],
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
