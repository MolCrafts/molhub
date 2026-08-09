import { HeadContent, Outlet, Scripts, createRootRoute } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { THEME_BOOTSTRAP } from "@/lib/theme";
import mokoUrl from "@brand/moko.svg";
import "@/styles/tailwind.css";

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      {
        title: "MolHub — datasets, models, and plugins",
      },
      {
        name: "description",
        content: "Find molecular datasets, models, and plugins for Python and the command line.",
      },
      { name: "theme-color", content: "#123720" },
    ],
    links: [{ rel: "icon", type: "image/svg+xml", href: mokoUrl }],
  }),
  component: RootLayout,
  shellComponent: RootDocument,
  notFoundComponent: NotFoundPage,
});

function RootLayout() {
  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <SkipToContent />
      <SiteHeader />
      <main id="main" className="flex-1 outline-none" tabIndex={-1}>
        <Outlet />
      </main>
      <SiteFooter />
    </div>
  );
}

function RootDocument({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <HeadContent />
        <script suppressHydrationWarning>{THEME_BOOTSTRAP}</script>
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function SkipToContent() {
  return (
    <a
      href="#main"
      className="sr-only z-50 rounded-control bg-accent px-4 py-2 text-accent-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
    >
      Skip to content
    </a>
  );
}

function NotFoundPage() {
  return (
    <section className="page-shell py-24">
      <p className="font-mono text-accent-ink text-sm">404 / unresolved</p>
      <h1 className="mt-3 font-display font-semibold text-4xl tracking-tight">
        This coordinate is not in the registry.
      </h1>
      <p className="mt-4 max-w-xl text-muted-foreground">
        The address may be incomplete, or the artifact may not have been published yet.
      </p>
    </section>
  );
}
