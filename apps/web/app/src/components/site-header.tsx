import { Link } from "@tanstack/react-router";
import { ArrowUpRight, Menu, X } from "lucide-react";
import { useState } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import mokoUrl from "@brand/moko.svg";

const links = [
  { label: "Registry", to: "/explore" },
  { label: "Submit", to: "/submit" },
] as const;

export function SiteHeader() {
  const [open, setOpen] = useState(false);

  return (
    <header className="brand-header sticky top-0 z-40 border-b">
      <div className="page-shell flex h-header items-center gap-5">
        <Link
          to="/"
          className="flex items-center gap-2 outline-none focus-visible:ring-2 focus-visible:ring-[var(--molcrafts-sand)]"
          onClick={() => setOpen(false)}
        >
          <MolhubMark />
          <span className="font-display font-bold text-lg tracking-tight">MolHub</span>
        </Link>

        <nav className="hidden items-center gap-1 md:flex" aria-label="Primary navigation">
          {links.map((item) => (
            <Link
              key={item.label}
              to={item.to}
              activeProps={{ className: "bg-white/12 text-white" }}
              className="rounded-control px-3 py-1.5 font-semibold text-sm text-white/72 transition-colors hover:bg-white/8 hover:text-white"
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1">
          <Button
            asChild
            variant="ghost"
            size="sm"
            className="hidden text-white/72 hover:bg-white/8 hover:text-white sm:inline-flex"
          >
            <a href="https://docs.molcrafts.org/molhub/" target="_blank" rel="noreferrer">
              Docs <ArrowUpRight aria-hidden="true" />
            </a>
          </Button>
          <ThemeToggle className="text-white/72 hover:bg-white/8 hover:text-white" />
          <Button
            variant="ghost"
            size="icon"
            className="text-white/72 hover:bg-white/8 hover:text-white md:hidden"
            aria-label={open ? "Close navigation" : "Open navigation"}
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
          </Button>
        </div>
      </div>

      <div
        className={cn(
          "page-shell overflow-hidden transition-[max-height,opacity] duration-200 ease-standard md:hidden",
          open ? "max-h-64 pb-3 opacity-100" : "max-h-0 opacity-0",
        )}
      >
        <nav className="grid gap-1 border-white/15 border-t pt-2" aria-label="Mobile navigation">
          {links.map((item) => (
            <Link
              key={item.label}
              to={item.to}
              className="rounded-control px-3 py-2 font-semibold text-sm text-white/78 hover:bg-white/8 hover:text-white"
              onClick={() => setOpen(false)}
            >
              {item.label}
            </Link>
          ))}
          <a
            href="https://docs.molcrafts.org/molhub/"
            className="rounded-control px-3 py-2 font-semibold text-sm text-white/78 hover:bg-white/8 hover:text-white"
          >
            Docs
          </a>
        </nav>
      </div>
    </header>
  );
}

function MolhubMark() {
  return (
    <span className="grid size-8 place-items-center rounded-control bg-[var(--molcrafts-cream)] shadow-raised">
      <img src={mokoUrl} alt="" className="size-6" />
    </span>
  );
}
