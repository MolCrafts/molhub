"""``molhub`` command line.

The verbs deliberately match the Python API and the planned TypeScript client:
``search`` / ``info`` / ``fetch`` mean the same thing everywhere, so moving
between the three does not mean relearning the vocabulary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from molhub.coordinate import InvalidCoordinate
from molhub.index import UnknownArtifact
from molhub.manifest import InvalidManifest
from molhub.molhub import Molhub
from molhub.registry import BlobStore, Digest, RegistryError

app = typer.Typer(
    name="molhub",
    help="Fetch molecular datasets, models, and plugins by coordinate.",
    no_args_is_help=True,
    add_completion=True,
)
cache_app = typer.Typer(name="cache", help="Inspect the local content-addressed cache.")
app.add_typer(cache_app)

_IndexOption = Annotated[
    Optional[Path],
    typer.Option("--index", help="Index directory to read. Defaults to $MOLHUB_INDEX."),
]


def _hub(index: Path | None) -> Molhub:
    """Build a hub, turning a broken index into a clean error rather than a traceback."""
    try:
        return Molhub(index)
    except InvalidManifest as error:
        raise typer.BadParameter(str(error)) from error


def _resolve(hub: Molhub, coordinate: str):
    """Resolve, mapping the two user-facing failures onto exit code 1."""
    try:
        return hub.resolve(coordinate)
    except (InvalidCoordinate, UnknownArtifact) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error


@app.command()
def search(
    query: Annotated[Optional[str], typer.Argument(help="Substring to look for.")] = None,
    kind: Annotated[
        Optional[str], typer.Option("--kind", help="dataset, model, or plugin.")
    ] = None,
    index: _IndexOption = None,
) -> None:
    """List artifacts matching QUERY."""
    matches = _hub(index).search(kind=kind, query=query)
    if not matches:
        typer.secho("No artifacts matched.", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)
    width = max(len(m.coordinate.canonical) for m in matches)
    for manifest in matches:
        typer.echo(
            f"{manifest.coordinate.canonical:<{width}}  {manifest.title}"
            f"{'  ' + manifest.license if manifest.license else ''}"
        )


@app.command()
def info(
    coordinate: Annotated[str, typer.Argument(help="Full or shorthand coordinate.")],
    index: _IndexOption = None,
) -> None:
    """Show everything the index knows about COORDINATE."""
    manifest = _resolve(_hub(index), coordinate)
    typer.echo(manifest.coordinate.canonical)
    typer.echo(f"  title      {manifest.title}")
    if manifest.description:
        typer.echo(f"  about      {manifest.description}")
    if manifest.license:
        typer.echo(f"  license    {manifest.license}")
    if manifest.citation:
        typer.echo(f"  cite       {manifest.citation}")
    if manifest.targets.graph_level:
        typer.echo(f"  graph      {', '.join(manifest.targets.graph_level)}")
    if manifest.targets.atom_level:
        typer.echo(f"  atom       {', '.join(manifest.targets.atom_level)}")
    for role, artifact in manifest.artifacts.items():
        size = f"  {artifact.size} B" if artifact.size else ""
        typer.echo(f"  [{role}] {artifact.filename}{size}")
        if artifact.digest:
            typer.echo(f"    {artifact.digest}")
        for locator in artifact.locators:
            typer.echo(f"    - {locator}")


@app.command()
def fetch(
    coordinate: Annotated[str, typer.Argument(help="Full or shorthand coordinate.")],
    into: Annotated[
        Optional[Path], typer.Option("--into", help="Also copy the files into this directory.")
    ] = None,
    index: _IndexOption = None,
) -> None:
    """Download COORDINATE's files, verifying each against its digest."""
    hub = _hub(index)
    manifest = _resolve(hub, coordinate)
    try:
        paths = hub.fetch(manifest.coordinate)
    except RegistryError as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    for role, path in paths.items():
        destination = path
        if into is not None:
            into.mkdir(parents=True, exist_ok=True)
            destination = into / manifest.artifact(role).filename
            destination.write_bytes(path.read_bytes())
        typer.echo(f"{role}\t{destination}")


@cache_app.command("verify")
def cache_verify(
    index: _IndexOption = None,
    home: Annotated[
        Optional[Path], typer.Option("--home", help="Cache root. Defaults to $MOLHUB_HOME.")
    ] = None,
) -> None:
    """Re-check cached files against the digests their manifests name.

    Files whose manifest records no digest are counted and skipped: the
    platform published nothing to check them against.
    """
    store = BlobStore(home)
    hub = _hub(index)

    checked = skipped = stale = 0
    for manifest in hub.search():
        for role, artifact in manifest.artifacts.items():
            path = store.path_for(f"{manifest.coordinate.canonical}/{role}")
            if not path.is_file():
                continue
            if artifact.digest is None:
                skipped += 1
                continue
            checked += 1
            actual = Digest.of_file(path, algorithm=artifact.digest.algorithm)
            if not actual.matches(artifact.digest):
                stale += 1
                typer.secho(
                    f"stale  {manifest.coordinate.canonical} [{role}]  {path}",
                    fg=typer.colors.RED,
                    err=True,
                )

    if not checked and not skipped:
        typer.echo(f"Nothing cached under {store.root}.")
        return
    typer.echo(f"{checked} checked, {stale} stale, {skipped} without a published digest.")
    if stale:
        raise typer.Exit(code=1)
