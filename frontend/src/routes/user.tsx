import { createFileRoute, Link } from "@tanstack/react-router";
import { PageLayout } from "./__root";

export const Route = createFileRoute("/user")({
  component: UserPage,
});

function UserPage() {
  return (
    <PageLayout>
      <section className="hero" aria-labelledby="user-title">
        <p className="eyebrow">VISION ASSISTANT · USER APP</p>
        <h1 id="user-title">Move through your day with more confidence.</h1>
        <p className="hero-copy">
          Your accessible space for camera assistance and support.
        </p>
      </section>

      <section className="content-grid" aria-label="User assistance">
        <article className="panel primary-panel">
          <div className="panel-heading">
            <span className="status-dot" aria-hidden="true" />
            <span className="eyebrow">ASSISTANCE STATUS</span>
          </div>
          <h2>Ready when you are</h2>
          <p>
            The user interface is ready. Camera and live assistance controls
            will be available when the session service is connected.
          </p>
          <div className="status-message" role="status">
            No active camera session
          </div>
        </article>

        <article className="panel support-panel">
          <p className="eyebrow">NEED A HAND?</p>
          <h2>Stay connected to your support person.</h2>
          <p>
            Open the guardian view to see the companion interface.
          </p>
          <Link className="text-link" to="/guardian">
            View guardian dashboard <span aria-hidden="true">→</span>
          </Link>
        </article>
      </section>
    </PageLayout>
  );
}
