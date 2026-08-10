import { Link } from "@tanstack/react-router";

export function SiteFooter() {
  const registryRevision = process.env.PUBLIC_MOLHUB_REGISTRY_REVISION;
  return (
    <footer className="brand-footer border-t">
      <div className="page-shell flex flex-col gap-4 py-6 text-sm sm:flex-row sm:items-center">
        <p className="font-display font-bold">MolHub</p>
        <nav className="flex flex-wrap gap-x-5 gap-y-2 text-white/68" aria-label="Footer">
          <Link to="/explore" className="hover:text-white">
            Registry
          </Link>
          <Link to="/submit" className="hover:text-white">
            Create manifest
          </Link>
          <a href="https://docs.molcrafts.org/molhub/" className="hover:text-white">
            Docs
          </a>
          <a href="https://github.com/MolCrafts/molhub" className="hover:text-white">
            GitHub
          </a>
        </nav>
        <span className="text-white/48 text-xs sm:ml-auto">
          {registryRevision ? (
            <a
              href={`https://github.com/MolCrafts/molhub-registry/commit/${registryRevision}`}
              className="font-mono hover:text-white"
              title={`Registry revision ${registryRevision}`}
            >
              registry {registryRevision.slice(0, 12)}
            </a>
          ) : (
            "local registry"
          )}
          {" · BSD-3-Clause"}
        </span>
      </div>
    </footer>
  );
}
