import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, forward /api calls to the detector service.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});
