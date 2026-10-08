import { createFileRoute } from "@tanstack/react-router";
import { GuardianDashboard } from "@/features/guardian/GuardianDashboard";

export const Route = createFileRoute("/guardian")({
  head: () => ({
    meta: [
      { title: "Guardian" },
      { name: "description", content: "Live status and alerts for your person." },
    ],
  }),
  component: GuardianDashboard,
});
