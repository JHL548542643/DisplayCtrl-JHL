import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function apiTarget(env: Record<string, string>): string {
  const raw = (env.VITE_API_BASE || "http://127.0.0.1:8765").trim().replace(/\/$/, "");
  if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(raw)) {
    throw new Error(`VITE_API_BASE 只能是本机回环地址，收到：${raw}`);
  }
  return raw;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const target = apiTarget(env);
  const proxy = { "/api": { target } };
  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: false,
      proxy,
    },
    preview: {
      host: "127.0.0.1",
      port: 4173,
      strictPort: true,
      proxy,
    },
  };
});
