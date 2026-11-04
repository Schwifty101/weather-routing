/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the Django API runs on :8000; the proxy keeps the browser same-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.API_TARGET ?? "http://127.0.0.1:8000", changeOrigin: true } },
  },
  build: { chunkSizeWarningLimit: 700 },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
