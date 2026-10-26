import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // Training tools and their scratch output are huge and change constantly; don't watch them.
    watch: { ignored: ["**/.tools/**", "**/work/**", "**/data/**", "**/assets/videos/**"] },
  },
  optimizeDeps: {
    // Pre-bundle Spark up front so its first dynamic import doesn't trigger a dependency re-optimise and reload.
    include: ["@sparkjsdev/spark"],
  },
});
