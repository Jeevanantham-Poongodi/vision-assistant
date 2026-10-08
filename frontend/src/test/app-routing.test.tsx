import fs from "node:fs";
import path from "node:path";
import { QueryClient } from "@tanstack/react-query";
import { createRouter, rootRouteId } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";

import { routeTree } from "@/routeTree.gen";

// Match routes without running loaders or rendering: loaders may need a server or
// network the test run lacks, and jsdom never loads the stylesheets React waits on.
describe("App routing", () => {
  it("matches a page for / instead of falling back to not found", () => {
    const router = createRouter({ routeTree, context: { queryClient: new QueryClient() } });

    const matches = router.matchRoutes("/");

    expect(matches.at(-1)?.routeId).not.toBe(rootRouteId);
  });

  it("matches the guardian dashboard route", () => {
    const router = createRouter({ routeTree, context: { queryClient: new QueryClient() } });

    const matches = router.matchRoutes("/guardian");

    expect(matches.at(-1)?.routeId).toBe("/guardian");
  });

  it("does not force mock data in the live app configuration", () => {
    const envPath = path.resolve(__dirname, "../../.env");
    const env = fs.readFileSync(envPath, "utf8");

    expect(env).not.toContain("VITE_USE_MOCKS=true");
  });
});
