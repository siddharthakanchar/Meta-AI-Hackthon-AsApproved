"""`asapproved <command>` — the CLI surface.

Phase 0 ships the skeleton plus a working `doctor`. Later phases fill in the
commands; each one raises a clear "not built yet (Phase N)" message until then.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from asapproved import RULEBOOK_VERSION, __version__
from asapproved.config import settings

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="AsApproved — measure whether approved risk warnings survive Meta's AI ad edits.",
)
console = Console()


def _todo(phase: str, what: str) -> None:
    console.print(f"[yellow]Not built yet[/] — {what} lands in {phase}.")
    raise typer.Exit(code=2)


@app.command()
def version() -> None:
    """Print the version and active rulebook."""
    console.print(f"asapproved {__version__} · rulebook {RULEBOOK_VERSION}")


@app.command()
def doctor() -> None:
    """Show config, credential presence (masked) and tool availability."""
    import shutil

    t = Table(title="AsApproved · doctor", show_lines=False)
    t.add_column("setting", style="cyan", no_wrap=True)
    t.add_column("value")
    for k, v in settings.redacted().items():
        t.add_row(k, str(v))
    console.print(t)

    tools = Table(title="external tools")
    tools.add_column("tool", style="cyan")
    tools.add_column("status")
    for tool in ("git", "ffmpeg", "ffprobe", "docker"):
        found = shutil.which(tool)
        tools.add_row(tool, f"[green]{found}[/]" if found else "[red]missing[/]")
    console.print(tools)

    console.print(
        f"\nmode=[bold]{settings.mode}[/] "
        + ("(offline: model calls must hit cache)" if settings.offline else "(live calls allowed)")
    )


@app.command()
def init_dirs() -> None:
    """Create the data/ tree."""
    settings.ensure_dirs()
    console.print(f"[green]ok[/] data tree ready under {settings.data_dir}")


@app.command()
def keygen(force: bool = typer.Option(False, help="Overwrite an existing key.")) -> None:
    """Generate the Ed25519 key used to sign approval manifests (C1)."""
    from asapproved.manifest import generate_key

    path = settings.signing_key_path
    try:
        generate_key(path, force=force)
    except FileExistsError:
        console.print(
            f"[yellow]A signing key already exists at[/] {path}\n"
            "Overwriting it invalidates every manifest signed with it. "
            "Pass --force only if that is what you want."
        )
        raise typer.Exit(code=1) from None
    console.print(f"[green]ok[/] wrote {path} and {path.name}.pub")
    console.print("[dim]The private key is unencrypted (demo compromise) and gitignored.[/]")


@app.command()
def approve(
    master: str = typer.Argument(..., help="Path to the approved master asset."),
    approver: str = typer.Option(..., "--approver", help="Who signed this off."),
    investment_type: str = typer.Option(
        None,
        "--investment-type",
        help="Selects the prescribed warning (COBS 4.12A.11R has four variants).",
    ),
    placement: list[str] = typer.Option(None, "--placement", help="Placements this covers."),
    notes: str = typer.Option("", "--notes"),
    out: str = typer.Option(None, "--out", help="Manifest path. Defaults alongside the master."),
) -> None:
    """Approve a master and write a signed approval manifest (C1)."""
    from asapproved.manifest import ApprovalManifest, sign_manifest

    master_path = Path(master)
    if not master_path.exists():
        console.print(f"[red]no such master:[/] {master_path}")
        raise typer.Exit(code=1)
    if not settings.signing_key_path.exists():
        console.print("[red]no signing key[/] — run `asapproved keygen` first.")
        raise typer.Exit(code=1)

    manifest = ApprovalManifest.for_master(
        master_path,
        approver=approver,
        investment_type=investment_type,
        placements=list(placement or []),
        notes=notes,
    )
    target = Path(out) if out else master_path.with_suffix(master_path.suffix + ".manifest.json")
    sign_manifest(manifest, settings.signing_key_path).write(target)

    console.print(f"[green]approved[/] {manifest.master_id}")
    console.print(f"  sha256     {manifest.master_sha256}")
    console.print(f"  approver   {manifest.approver}")
    console.print(f"  at         {manifest.approved_at}")
    console.print(f"  rulebook   {manifest.rulebook_version}")
    console.print(f"  manifest   {target}")
    if not manifest.enhancement_settings:
        console.print(
            "[yellow]note[/] no enhancement settings recorded — R2 (settings drift) cannot "
            "fire without a baseline. These are captured from the Marketing API in Phase 6."
        )


@app.command()
def verify_manifest(
    path: str = typer.Argument(...),
    master: str = typer.Option(None, "--master", help="Also re-hash this master and compare."),
    trusted_key: str = typer.Option(
        None, "--trusted-key", help="Pin the expected signer's public key (PEM)."
    ),
) -> None:
    """Verify a signed approval manifest (C1)."""
    from asapproved.manifest import verify_manifest as _verify

    result = _verify(path, trusted_public_key=trusted_key, master_path=master)
    if result.ok:
        console.print(f"[green]VALID[/] {result.reason}")
        if not result.key_pinned:
            console.print(
                "[yellow]warning[/] no trusted key pinned: this proves the manifest is "
                "internally consistent, not who signed it. Pass --trusted-key for that."
            )
        raise typer.Exit(code=0)
    console.print(f"[red]INVALID[/] {result.reason}")
    raise typer.Exit(code=1)


@app.command()
def verify_log(path: str = typer.Argument(...)) -> None:
    """Verify an evidence log's hash chain, naming the first broken record (C12)."""
    from asapproved.evidence import verify_chain

    result = verify_chain(path)
    if result.ok:
        console.print(f"[green]INTACT[/] {result.entries} records, chain unbroken")
        console.print(f"  head {result.head}")
        raise typer.Exit(code=0)
    console.print(f"[red]TAMPERED[/] {result.reason}")
    if result.first_bad_line is not None:
        console.print(f"  first bad record  index {result.first_bad_index}, line {result.first_bad_line}")
        console.print(f"  records verified before the break: {result.entries}")
    raise typer.Exit(code=1)


@app.command()
def check(variant: str = typer.Argument(..., help="Path to a variant asset.")) -> None:
    """Run the full pipeline on one variant and emit findings JSON (Phase 4)."""
    _todo("Phase 4", "the end-to-end variant check")


@app.command()
def drift() -> None:
    """Read live enhancement settings and diff against approval manifests (D1, Phase 6)."""
    _todo("Phase 6", "the settings-drift monitor")


@app.command()
def blast_radius(finding: str = typer.Argument(...)) -> None:
    """List every sibling ad sharing the asset and feature (D2, Phase 6)."""
    _todo("Phase 6", "blast-radius lookup")


@app.command()
def bench() -> None:
    """Run VariantBench-UK: B0 vs B1 vs B2 (D5, Phase 6)."""
    _todo("Phase 6", "the benchmark harness")


@app.command()
def demo() -> None:
    """Replay the hero case entirely from cache — no keys, no network (quality gate §13)."""
    _todo("Phase 7", "the cached hero-case demo")


if __name__ == "__main__":
    app()
