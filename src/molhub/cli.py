"""``molhub`` command line.

The verbs deliberately match the Python API and the planned TypeScript client:
``search`` / ``info`` / ``fetch`` mean the same thing everywhere, so moving
between the three does not mean relearning the vocabulary.

``info`` is **content first** (``hf-facade-04-streaming-prepare`` ac-006): what a
record carries and which splits exist, sourced from
:attr:`~molhub.loader.builder.DatasetBuilder.info` — the same answer the Python
API gives, rather than a second rendering of the manifest. Roles, filenames,
sizes, digests and locators are transport, and transport moved behind
``--files``. Neither view prints an example record: producing one would cost the
bytes of a whole artifact — tens of GiB to several TiB — to show one molecule,
and ``info`` staying free is worth more. It *is* free for every dataset whose
splits a published derivation states; for the few whose class owns its splits
the count is the dataset's own ``len``, which costs what reading it costs — that
price is :class:`~molhub.loader.builder.DatasetBuilder`'s, stated in its
docstring, and this verb inherits it rather than inventing a second, cheaper
answer.

**That asymmetry is said out loud, before it is spent** (reachability wave,
ruling 7). A docstring is not where a reader finds out that describing a dataset
downloaded a benchmark: ``--help`` says a description can download, and the byte
total reaches **stderr** before anything is fetched — stderr, so a piped report
is unchanged by the warning. The notice itself is now the *library's*
(:class:`~molhub.loader.mapstyle.DownloadNotice`, printed by
:attr:`~molhub.loader.builder.DatasetBuilder.info`), not this module's: a
notebook and a training script call the same describing path and never see a CLI
warning, and two layers stating one sentence is one notice printed twice at the
terminal — which is how a warning becomes noise, and noise is how the real one
gets skipped. ``--home`` joins it for parity with ``cache status`` /
``cache verify``: the split derivation ``info`` reads lives under the cache root,
and with only ``$MOLHUB_HOME`` to go on there is no way to point this verb at a
second molhub home without exporting a variable around it.

**Byte counts are rendered by the library's own type.**
``download 31041658614 B`` is a number a reader counts digits on; the same line
now leads with :class:`~molhub.loader.info.ByteSize`'s ``28.9 GiB`` and keeps the
raw count in parentheses, because a script greps the number and a human reads the
unit. It is the type :meth:`~molhub.loader.info.DatasetInfo.__str__` prints, not
a second formatter that agrees with it today — the same promotion
``default_ledger_path`` and ``DEFAULT_BUDGET_BYTES`` already had. The stderr
notice renders through the very same type, one layer down, so the number a
reader weighs before the download and the number the report prints after it are
one spelling of one fact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

from molhub.conveyor import DEFAULT_BUDGET_BYTES, ConveyorError, default_ledger_path
from molhub.coordinate import InvalidCoordinate
from molhub.loader import AmbiguousRevision, SplitTableUnavailable
from molhub.loader.builder import DatasetBuilder
from molhub.loader.info import ByteSize, DatasetInfo
from molhub.manifest import InvalidManifest, Manifest
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

# The conveyor's two tiers, spelled here because the CLI is where a user's
# `--home` becomes a path. Neither tier is under `files/`, which stays the
# cross-client layout the TypeScript client reads. The bookkeeping file and the
# rolling budget are *not* spelled here any more: `molhub.conveyor` states both,
# because a streaming walk writes the same file and two defaults would
# desynchronize the claims `cache coverage` replays.
_RAW_SUBDIR = "conveyor/raw"
_BLOCKS_SUBDIR = "conveyor/blocks"


def _hub(registry: Path | None) -> Molhub:
    """Build a hub, turning a broken registry into a clean error rather than a traceback."""
    try:
        return Molhub(registry)
    except InvalidManifest as error:
        raise typer.BadParameter(str(error)) from error


def _resolve(hub: Molhub, coordinate: str) -> Manifest:
    """Resolve, mapping the two user-facing failures onto exit code 1."""
    try:
        return hub.resolve(coordinate)
    except (InvalidCoordinate, UnknownArtifact) as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error


def _describe(hub: Molhub, name: str, home: Path | None) -> DatasetInfo:
    """What *name* contains, from the same authority the Python API reports.

    The argument is accepted in either spelling a user is likely to type — the
    HuggingFace one (``themol/mbis``) and the coordinate one
    (``dataset:themol/mbis@1``) — because the two verbs beside this one have
    always taken the second and the Python API takes the first. The ``@version``
    is split off here rather than inside
    :class:`~molhub.loader.naming.DatasetName`, which refuses it on purpose so
    that one name has one spelling on that path.

    What describing costs is announced on stderr before it is spent — by the
    builder itself, so a notebook calling the same path is warned too, and so
    that one command prints one notice. For a dataset whose splits nobody
    published a table for, the counts are the dataset's own ``len``, and the
    description *is* the download.

    Args:
        hub: The resolved registry.
        name: The dataset name or coordinate, as typed.
        home: Cache root the split derivation is read from; ``None`` uses
            ``$MOLHUB_HOME``.

    Returns:
        The description — content only, and never a file role.

    Raises:
        typer.Exit: With code 1 when the name is malformed, is not declared,
            declares versions that do not order, takes its splits from a
            derivation this machine has not built, has one that does not verify,
            or — for a dataset whose class owns its splits, and whose counts are
            therefore its own — cannot be read. Each of those is something the
            reader can act on, and a traceback would bury it.
    """
    text, separator, revision = name.partition("@")
    try:
        builder = DatasetBuilder(
            text,
            revision=revision if separator else None,
            registry=hub.registry,
            hub=hub,
            home=home,
        )
        return builder.info
    except (
        InvalidCoordinate,
        UnknownArtifact,
        AmbiguousRevision,
        SplitTableUnavailable,
        ConveyorError,
        SourceError,
    ) as error:
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
    name: Annotated[
        str,
        typer.Argument(
            help="Dataset name (themol/mbis), optionally with @version, or a full coordinate."
        ),
    ],
    files: Annotated[
        bool,
        typer.Option("--files", help="Also list the artifact's roles, digests and locators."),
    ] = False,
    registry: _RegistryOption = None,
    home: _HomeOption = None,
) -> None:
    """Show what NAME contains — and, with --files, which files carry it.

    Describing some datasets downloads them: where no split table is published,
    the split counts are the dataset's own and reading them is the only way to
    have them. The byte total is printed to stderr before that happens.
    """
    hub = _hub(registry)
    described = _describe(hub, name, home)
    manifest = _resolve(hub, described.coordinate.canonical)

    typer.echo(described.coordinate.canonical)
    typer.echo(f"  title      {manifest.title}")
    if described.description:
        typer.echo(f"  about      {described.description}")
    if described.license:
        typer.echo(f"  license    {described.license}")
    if described.citation:
        typer.echo(f"  doi        {described.citation}")
    typer.echo(f"  record     {described.record_type}")
    typer.echo(f"  download   {ByteSize(described.download_size)} ({described.download_size} B)")
    for feature in described.features:
        units = f"  {feature.units}" if feature.units else ""
        typer.echo(f"  feature    {feature.name}  [{feature.level}]{units}")
    for split in described.splits:
        typer.echo(
            f"  split      {split.name}  {split.num_examples} "
            f"{_plural(split.num_examples, 'record', 'records')}"
        )
    if described.splits:
        typer.echo(f"  splits from {described.splits[0].provenance}")
    if not files:
        return
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
    ] = DEFAULT_BUDGET_BYTES,
    budget_blocks: Annotated[
        int, typer.Option("--budget-blocks", help="Byte budget for the sealed block tier.")
    ] = DEFAULT_BUDGET_BYTES,
) -> None:
    """Report how much disk the cache holds, against its byte budget.

    One line per pile of cached files — entries, bytes on disk, bytes budgeted —
    then a summary. Exits 1 when a pile holds more than its byte budget allows:
    that is the bounded-residency invariant failing on disk, and a status verb
    that reported it with exit 0 would be one nothing could gate on.
    """
    # Imported here, not at module scope: `molhub search` should not pay for the
    # conveyor's numpy import, and `molhub.dataset.neighbor` set this precedent.
    from molhub.conveyor import Ledger, TierStore

    root = BlobStore(home).root
    ledger = Ledger(default_ledger_path(root))
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
        ledger = Ledger(default_ledger_path(root))
        records = ledger.records()
        blocks = TierStore(
            root, subdir=_BLOCKS_SUBDIR, budget_bytes=DEFAULT_BUDGET_BYTES, ledger=ledger
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
        RosterError: If a manifest declares shards but cannot honestly be
            projected into a roster — an unsized or undigested shard is a
            defect the coverage number would otherwise hide.
    """
    from molhub.conveyor import BlockRoster, NoShardArtifacts
    from molhub.dataset.universal_class_i import Class1Universal2026

    total = 0
    for role in Class1Universal2026().load().roles:
        for coordinate in role.source_coordinates:
            try:
                manifest = hub.resolve(coordinate)
            except (InvalidCoordinate, UnknownArtifact):
                continue
            try:
                total += len(BlockRoster(manifest, role).blocks())
            except NoShardArtifacts:
                # Whole-artifact sources (OMol25-small, PhAlkEthOH-MM) publish
                # no `shard-N` roles: they are fetched whole on the hot tier and
                # are not part of the byte-bounded rolling corpus. The loud
                # refusal stays for the conveyor pipeline, where an unsharded
                # manifest under a sharded collection is a real defect.
                continue
    return total
