import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv, type ProxyOptions } from "vite";

function apiProxy(target: string): Record<string, ProxyOptions> {
  return {
    "/api": {
      target,
      changeOrigin: true,
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendUrl = env.BACKEND_URL || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    server: {
      host: "0.0.0.0",
      port: 3000,
      strictPort: true,
      proxy: apiProxy(backendUrl),
    },
    preview: {
      host: "0.0.0.0",
      port: 3000,
      strictPort: true,
      proxy: apiProxy(backendUrl),
    },
  };
});
