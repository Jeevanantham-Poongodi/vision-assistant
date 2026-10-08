/** Dev-only host for Coder 4's speech test page (src/features/voice/*). */
import { ClientOnly, createFileRoute } from "@tanstack/react-router";
import { lazy, Suspense, type ComponentType } from "react";
import { config } from "@/services/config";

const pages = import.meta.glob<{ default?: ComponentType }>("/src/features/voice/**/*.tsx");
const key =
  Object.keys(pages).find((k) => /speech.*test|test.*page|devspeech/i.test(k)) ?? Object.keys(pages)[0];
const VoicePage = key
  ? lazy(async () => {
      const loader = pages[key];
      const m = loader ? await loader() : {};
      return { default: m.default ?? (() => <p>No default export in {key}</p>) };
    })
  : null;

export const Route = createFileRoute("/dev/speech")({
  head: () => ({
    meta: [
      { title: "Speech test (dev)" },
      { name: "description", content: "Developer page for the speech service." },
      { property: "og:title", content: "Speech test (dev)" },
      { property: "og:description", content: "Developer page for the speech service." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: DevSpeech,
});

function DevSpeech() {
  if (!config.isDev) return <p className="p-8 text-xl">Not available in production.</p>;
  if (!VoicePage)
    return (
      <p className="p-8 text-xl">
        Coder 4's speech test page is not in <code>src/features/voice/</code> yet.
      </p>
    );
  return (
    <ClientOnly fallback={null}>
      <Suspense fallback={<p className="p-8">Loading…</p>}>
        <VoicePage />
      </Suspense>
    </ClientOnly>
  );
}
