import { fileURLToPath, URL } from "node:url";

import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const target = env.VITE_PROXY_TARGET || "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      host: "0.0.0.0",
      port: 5173,
      strictPort: false,
      // The Arena preview (and any reverse proxy) controls the Host header.
      allowedHosts: true,
      proxy: {
        "/api": { target, changeOrigin: true, ws: true },
        "/media": { target, changeOrigin: true },
      },
    },
    preview: {
      host: "0.0.0.0",
      port: 4173,
      allowedHosts: true,
      proxy: {
        "/api": { target, changeOrigin: true, ws: true },
        "/media": { target, changeOrigin: true },
      },
    },
    build: {
      outDir: "dist",
      sourcemap: false,
      chunkSizeWarningLimit: 900,
    },
    test: {
      environment: "jsdom",
      globals: true,
      css: false,
      setupFiles: ["./src/test/setup.ts"],
      environmentOptions: {
        jsdom: { url: "http://127.0.0.1:8000" },
      },
      testTimeout: 30_000,
      hookTimeout: 30_000,
      include: ["src/test/**/*.test.{ts,tsx}"],
    },
  };
});
