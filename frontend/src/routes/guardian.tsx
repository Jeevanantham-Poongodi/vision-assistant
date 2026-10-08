import { createFileRoute, Link } from "@tanstack/react-router";
import { PageLayout } from "./__root";

export const Route = createFileRoute("/guardian")({
  component: GuardianPage,
});

function GuardianPage() {
  return (
    <PageLayout>
      <section className="hero" aria-labelledby="guardian-title">
        <p className="eyebrow">VISION ASSISTANT · GUARDIAN</p>
        <h1 id="guardian-title">Guardian dashboard</h1>
        <p className="hero-copy">
          A clear view of the user session and support status.
        </p>
      </section>

      <section className="content-grid" aria-label="Guardian session">
        <article className="panel primary-panel">
          <div className="panel-heading">
            <span className="status-dot" aria-hidden="true" />
            <span className="eyebrow">SESSION STATUS</span>
          </div>
          <h2>No active user session</h2>
          <p>
            When a user session is connected, its live view and updates will
            appear here.
          </p>
          <div className="empty-state" role="status">
            Waiting for a user to connect
          </div>
        </article>

        <article className="panel support-panel">
          <p className="eyebrow">USER APP</p>
          <h2>Return to the user experience.</h2>
          <p>Open the accessible user screen.</p>
          <Link className="text-link" to="/user">
            View user app <span aria-hidden="true">→</span>
          </Link>
        </article>
      </section>
    </PageLayout>
  );
}
