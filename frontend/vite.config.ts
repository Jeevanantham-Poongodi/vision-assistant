// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";
import { createLogger } from "vite";

// The Lovable preset injects vite-tsconfig-paths internally, so Vite's suggestion to
// remove it can't be acted on here. Silence that one message.
const logger = createLogger();
const warn = logger.warn.bind(logger);
const warnOnce = logger.warnOnce.bind(logger);
const isTsconfigPathsNotice = (msg: string) => msg.includes("vite-tsconfig-paths");
logger.warn = (msg, opts) => {
  if (!isTsconfigPathsNotice(msg)) warn(msg, opts);
};
logger.warnOnce = (msg, opts) => {
  if (!isTsconfigPathsNotice(msg)) warnOnce(msg, opts);
};

export default defineConfig({
  tanstackStart: {
    // Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
    // nitro/vite builds from this
    server: { entry: "server" },
  },
  vite: {
    customLogger: logger,
  },
});
