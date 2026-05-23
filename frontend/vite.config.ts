import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";

const isLocalApiBaseUrl = (url: string) => /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(url);

function resolveApiBaseUrl(mode: string) {
  const env = loadEnv(mode, process.cwd(), "");
  const configuredUrl = env.VITE_API_BASE_URL?.trim() ?? "";

  // Vercel production should never bake localhost into the frontend bundle.
  // If no API URL is configured, or if it is accidentally set to localhost,
  // use an empty base URL so browser requests stay on the deployed origin.
  if (mode === "production" && (!configuredUrl || isLocalApiBaseUrl(configuredUrl))) {
    return "";
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
