import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": process.env.VITE_BACKEND_URL || "http://127.0.0.1:8080" } },
  // Live local mode keeps older hashed assets so a page loaded mid-rebuild works.
  build: process.env.DUKA_LIVE_WATCH ? { emptyOutDir: false } : {},
});
