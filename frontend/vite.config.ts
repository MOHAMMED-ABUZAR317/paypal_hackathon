import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs on FastAPI at :8000. In production FastAPI serves `dist/`
// itself, so relative /api calls work with no CORS setup.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // AG Grid alone is ~900 kB minified; it is deliberately isolated in its own
    // chunk, so the default 500 kB warning is not actionable here.
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        // AG Grid is the single biggest dependency; split it out so the shell
        // and the grid can be cached independently.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          aggrid: ["ag-grid-react", "ag-grid-community"],
        },
      },
    },
  },
});
