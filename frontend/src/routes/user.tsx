import { createFileRoute } from "@tanstack/react-router";
import { UserApp } from "@/features/user/UserApp";

export const Route = createFileRoute("/user")({
  head: () => ({
    meta: [
      { title: "User" },
      {
        name: "description",
        content: "Hands-free vision assistant that speaks hazards on your path.",
      },
      { property: "og:title", content: "User" },
      {
        property: "og:description",
        content: "Hands-free vision assistant that speaks hazards on your path.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
  component: UserApp,
});
