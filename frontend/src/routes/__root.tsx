import {
  createRootRoute,
  HeadContent,
  Outlet,
  Scripts,
} from "@tanstack/react-router";
import type { ReactNode } from "react";
import "../styles.css";

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "Vision Assistant" },
      {
        name: "description",
        content: "An accessible vision assistance interface.",
      },
    ],
  }),
  component: RootDocument,
});

function RootDocument() {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        <Outlet />
        <Scripts />
      </body>
    </html>
  );
}

export function PageLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/user" aria-label="Vision Assistant home">
          <span className="brand-mark" aria-hidden="true">
            V
          </span>
          <span>Vision Assistant</span>
        </a>
        <nav className="main-nav" aria-label="Main navigation">
          <a href="/user">User app</a>
          <a href="/guardian">Guardian</a>
        </nav>
      </header>
      <main>{children}</main>
      <footer className="site-footer">
        Vision Assistant <span aria-hidden="true">·</span> Accessible by design
      </footer>
    </div>
  );
}
