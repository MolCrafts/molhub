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
from molhub.manifest import InvalidManifest
from molhub.molhub import Molhub
from molhub.registry import UnknownArtifact
from molhub.sources import BlobStore, Digest, SourceError

app = typer.Typer(
    name="molhub",
    help="Fetch molecular datasets, models, and plugins by coordinate.",
    no_args_is_help=True,
    add_completion=True,
)
cache_app = typer.Typer(name="cache", help="Inspect the local cache, keyed by coordinate and role.")
app.add_typer(cache_app)

_RegistryOption = Annotated[
    Optional[Path],
    typer.Option("--registry", help="Registry directory to read. Defaults to $MOLHUB_REGISTRY."),
]
_HomeOption = Annotated[
    Optional[Path],
    typer.Option("--home", help="Cache root. Defaults to $MOLHUB_HOME."),
]

# The conveyor's two tiers and its ledger, spelled here because the CLI is where
# a user's `--home` becomes a path. Neither tier is under `files/`, which stays
# the cross-client layout the TypeScript client reads.
_RAW_SUBDIR = "conveyor/raw"
_BLOCKS_SUBDIR = "conveyor/blocks"
_LEDGER_SEGMENTS = ("conveyor", "ledger.jsonl")

# The strategy's per-tier rolling working set, restated in exactly one place;
# see `.claude/notes/streaming-data-tiers.md`.
_DEFAULT_BUDGET_BYTES = 40_000_000_000


def _hub(registry: Path | None) -> Molhub:
    """Build a hub, turning a broken registry into a clean error rather than a traceback."""
    try:
        return Molhub(registry)
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
    registry: _RegistryOption = None,
) -> None:
    """List artifacts matching QUERY."""
    matches = _hub(registry).search(kind=kind, query=query)
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
    registry: _RegistryOption = None,
) -> None:
    """Show everything the registry knows about COORDINATE."""
    manifest = _resolve(_hub(registry), coordinate)
    typer.echo(manifest.coordinate.canonical)
    typer.echo(f"  title      {manifest.title}")
    if manifest.description:
        typer.echo(f"  about      {manifest.description}")
    if manifest.license:
        typer.echo(f"  license    {manifest.license}")
    if manifest.doi:
        typer.echo(f"  doi        {manifest.doi}")
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
    registry: _RegistryOption = None,
) -> None:
    """Download COORDINATE's files, checking any digest the manifest records."""
    hub = _hub(registry)
    manifest = _resolve(hub, coordinate)
    try:
        paths = hub.fetch(manifest.coordinate)
    except SourceError as error:
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
    registry: _RegistryOption = None,
    home: _HomeOption = None,
) -> None:
    """Re-check cached files against the digests their manifests name.

    Files whose manifest records no digest are counted and skipped: the
    platform published nothing to check them against.
    """
    store = BlobStore(home)
    hub = _hub(registry)

    checked = skipped = stale = 0
    for manifest in hub.search():
        for role, artifact in manifest.artifacts.items():
            path = store.path_for(f"{manifest.coordinate.cache_path()}/{role}")
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


@cache_app.command("status")
def cache_status(
    home: _HomeOption = None,
    budget_raw: Annotated[
        int, typer.Option("--budget-raw", help="Byte budget for the raw shard tier.")
    ] = _DEFAULT_BUDGET_BYTES,
    budget_blocks: Annotated[
        int, typer.Option("--budget-blocks", help="Byte budget for the sealed block tier.")
    ] = _DEFAULT_BUDGET_BYTES,
) -> None:
    """Report each conveyor tier's residency against its own byte budget.

    One line per tier — entries, bytes resident, bytes budgeted — then a
    summary. Exits 1 when a tier holds more than its budget allows: that is the
    bounded-residency invariant failing on disk, and a status verb that reported
    it with exit 0 would be one nothing could gate on.
    """
    # Imported here, not at module scope: `molhub search` should not pay for the
    # conveyor's numpy import, and `molhub.dataset.neighbor` set this precedent.
    from molhub.conveyor import Ledger, TierStore

    root = BlobStore(home).root
    ledger = Ledger(root.joinpath(*_LEDGER_SEGMENTS))
    tiers = [
        ("raw", TierStore(root, subdir=_RAW_SUBDIR, budget_bytes=budget_raw, ledger=ledger)),
        (
            "blocks",
            TierStore(root, subdir=_BLOCKS_SUBDIR, budget_bytes=budget_blocks, ledger=ledger),
        ),
    ]
    present = [(name, store) for name, store in tiers if store.directory.is_dir()]
    if not present:
        typer.echo(f"No conveyor tiers under {root}.")
        return

    over = 0
    for name, store in present:
        breach = ""
        if store.resident_bytes > store.budget_bytes:
            over += 1
            breach = "  OVER BUDGET"
        entries = len(store.entries())
        typer.echo(
            f"{name:<7}{entries:>5} {_plural(entries, 'entry', 'entries'):<8}"
            f"{store.resident_bytes} B resident of {store.budget_bytes} B budget{breach}"
        )
    typer.echo(
        f"{len(present)} {_plural(len(present), 'tier', 'tiers')}, "
        f"{sum(store.resident_bytes for _, store in present)} B resident, {over} over budget."
    )
    if over:
        raise typer.Exit(code=1)


@cache_app.command("coverage")
def cache_coverage(
    registry: _RegistryOption = None,
    home: _HomeOption = None,
) -> None:
    """Report what this run has seen, against the corpus the registry declares.

    Replays the conveyor ledger under ``<home>/conveyor/ledger.jsonl`` and
    prints blocks seen, blocks consumed as a share of the corpus, units seen and
    the byte totals. The denominator is the block roster projected from the
    registry's own manifests; without one the verb exits 1 rather than printing
    a coverage number nobody can interpret, which is precisely the implicit
    coverage the strategy's I10 forbids.
    """
    from molhub.conveyor import ConveyorError, CoverageReport, Ledger, ReadyBlocks, TierStore

    hub = _hub(registry)
    root = BlobStore(home).root
    try:
        total = _corpus_blocks(hub)
        if not total:
            typer.secho(
                "No block roster: this registry publishes none of the collection's pinned "
                "sources, so there is no corpus to measure coverage against. Point --registry "
                "at one that carries them.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        ledger = Ledger(root.joinpath(*_LEDGER_SEGMENTS))
        records = ledger.records()
        blocks = TierStore(
            root, subdir=_BLOCKS_SUBDIR, budget_bytes=_DEFAULT_BUDGET_BYTES, ledger=ledger
        )
        units_by_block = {item.block_id: item.units for item in ReadyBlocks(blocks).metadata()}
    except ConveyorError as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    report = CoverageReport.replay(records, units_by_block=units_by_block)
    typer.echo(
        f"blocks seen {len(report.blocks_seen)}, consumed {len(report.blocks_consumed)} of "
        f"{total} ({report.fraction(total):.1%}), units seen {report.units_seen}"
    )
    typer.echo(
        f"bytes downloaded {report.bytes_downloaded}, prepared {report.bytes_prepared}, "
        f"evicted {report.bytes_evicted}, raw released {report.bytes_raw_released}"
    )


def _plural(count: int, singular: str, plural: str) -> str:
    """The noun *count* takes, so a report does not say "1 entries"."""
    return singular if count == 1 else plural


def _corpus_blocks(hub: Molhub) -> int:
    """How many remote blocks this registry declares for the Class-I collection.

    Args:
        hub: The resolved registry.

    Returns:
        The block count across every collection role whose pinned source this
        registry carries. A coordinate it does not publish is skipped: it is not
        part of this machine's corpus, and guessing a denominator is worse than
        reporting a smaller one.

    Raises:
        RosterError: If a manifest is present but cannot honestly be projected
            into a roster — an unsized or undigested shard is a defect the
            coverage number would otherwise hide.
    """
    from molhub.conveyor import BlockRoster
    from molhub.dataset.universal_class_i import Class1Universal2026

    total = 0
    for role in Class1Universal2026().load().roles:
        for coordinate in role.source_coordinates:
            try:
                manifest = hub.resolve(coordinate)
            except (InvalidCoordinate, UnknownArtifact):
                continue
            total += len(BlockRoster(manifest, role).blocks())
    return total
