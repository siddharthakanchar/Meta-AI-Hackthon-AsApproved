"""`asapproved <command>` — the CLI surface.

Phase 0 ships the skeleton plus a working `doctor`. Later phases fill in the
commands; each one raises a clear "not built yet (Phase N)" message until then.
"""

from __future__ import annotations

import json
import sys
import time
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

    from asapproved.ffmpeg import ffmpeg_path, ffprobe_path

    tools = Table(title="external tools")
    tools.add_column("tool", style="cyan")
    tools.add_column("status")
    for tool in ("git", "docker"):
        found = shutil.which(tool)
        tools.add_row(tool, f"[green]{found}[/]" if found else "[red]missing[/]")
    # ffmpeg gets the resolver, not `which`: winget updates PATH but open shells
    # keep the old one, so `which` says missing on a machine where it works.
    for name, resolver in (("ffmpeg", ffmpeg_path), ("ffprobe", ffprobe_path)):
        found = resolver(required=False)
        tools.add_row(name, f"[green]{found}[/]" if found else "[red]missing[/]")
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
def check(
    variant: str = typer.Argument(..., help="Path to a variant asset."),
    master: str = typer.Option(None, "--master", help="Master id. Inferred from the filename."),
    json_out: str = typer.Option(None, "--json", help="Write the full findings record here."),
) -> None:
    """Run the deterministic pipeline on one variant and report findings."""
    from asapproved.explain import template_note
    from asapproved.pipeline import check_variant, load_master

    path = Path(variant)
    if not path.exists():
        console.print(f"[red]no such variant:[/] {path}")
        raise typer.Exit(code=1)

    master_id = master or path.stem.split("__")[0]
    try:
        ref = load_master(master_id, settings.masters_dir)
    except FileNotFoundError:
        console.print(
            f"[red]no master sidecar for[/] {master_id} in {settings.masters_dir}\n"
            "Run scripts/make_masters.py, or pass --master."
        )
        raise typer.Exit(code=1) from None

    result = check_variant(path, ref)
    s = result.summary

    t = Table(title=f"{path.name}  vs  {master_id}")
    t.add_column("rule", style="cyan", no_wrap=True)
    t.add_column("status")
    t.add_column("measured", justify="right")
    t.add_column("threshold", justify="right")
    t.add_column("detail", max_width=60)
    colour = {"fail": "red", "pass": "green", "inconclusive": "yellow", "not_applicable": "dim"}
    for f in result.findings:
        t.add_row(
            f.rule_id,
            f"[{colour[f.status]}]{f.status}[/]",
            f.measured_display or "—",
            f.threshold_display or "—",
            f.detail,
        )
    console.print(t)

    console.print(
        f"\n[bold]{s['fail']}[/] failing · [yellow]{s['inconclusive']}[/] inconclusive · "
        f"{s['pass']} passing · {s['not_applicable']} n/a"
    )
    console.print(f"[dim]regions: {result.region_source} · text: {result.text_source}[/]")
    for note in result.notes:
        console.print(f"[dim]note: {note}[/]")
    console.print()
    console.print(template_note(result.findings))

    if json_out:
        out = Path(json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result.to_record(), indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"\n[green]wrote[/] {out}")

    raise typer.Exit(code=1 if result.blocking else 0)


@app.command()
def drift() -> None:
    """Read live enhancement settings and diff against approval manifests (D1, Phase 6)."""
    _todo("Phase 6", "the settings-drift monitor")


@app.command()
def blast_radius(
    variant: str = typer.Argument(..., help="Variant id, e.g. northfield_card_v2__v0_...")
) -> None:
    """Every other live ad sharing this asset AND enrolled in the enhancement."""
    from asapproved.act import plan_opt_out
    from asapproved.graph import build_from_lineage

    lineage = settings.data_dir / "lineage.json"
    runs_index = settings.data_dir / "runs" / "index.json"
    if not lineage.exists():
        console.print(
            "[red]no ad lineage[/] — build it with:\n  python scripts/make_lineage.py"
        )
        raise typer.Exit(code=1)

    graph = build_from_lineage(lineage, runs_index if runs_index.exists() else None)
    try:
        result = graph.blast_radius(variant)
    except KeyError:
        console.print(f"[red]unknown variant:[/] {variant}")
        console.print("[dim]list them with: asapproved demo, or see data/runs/index.json[/]")
        raise typer.Exit(code=1) from None

    console.print(f"[bold]{result.headline()}[/]  (enhancement: {result.feature})")
    console.print(
        "[dim]Siblings must share the asset AND be enrolled in the feature. Sharing the "
        "asset alone over-reports — an ad that opted out is not at risk from it.[/]\n"
    )

    if not result.siblings:
        console.print("[green]No other live ad uses this asset with this enhancement on.[/]")
        raise typer.Exit(code=0)

    t = Table()
    t.add_column("ad", style="cyan", no_wrap=True)
    t.add_column("master")
    t.add_column("placement")
    t.add_column("enrolment")
    t.add_column("already failing")
    for s in result.siblings:
        t.add_row(
            s.ad_id,
            s.master_id,
            s.placement or "—",
            s.enroll_status,
            "yes" if s.already_failing else "",
        )
    console.print(t)

    plan = plan_opt_out([s.ad_id for s in result.siblings], result.feature)
    console.print(f"\n[dim]Act would send {plan.count} opt-out request(s):[/]")
    console.print(json.dumps(plan.as_requests()[:1], indent=2))
    console.print(
        "[yellow]DRY RUN[/] — no Marketing API access, so nothing is sent and Prove "
        "reports 'could not verify', never 'proven'."
    )


@app.command()
def bench(
    limit: int = typer.Option(None, help="Score only the first N variants."),
    baselines: str = typer.Option("b1,b2", help="Which baselines to run."),
) -> None:
    """Run VariantBench-UK and write eval/report.md."""
    import subprocess

    cmd = [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "run_bench.py")]
    if limit:
        cmd += ["--limit", str(limit)]
    cmd += ["--baselines", baselines]
    raise typer.Exit(code=subprocess.call(cmd))


@app.command()
def demo() -> None:
    """Replay the hero case from cache — no keys, no network (quality gate §13)."""
    runs = settings.data_dir / "runs"
    index_path = runs / "index.json"
    if not index_path.exists():
        console.print(
            "[red]no cached runs[/] — build them with:\n"
            "  python scripts/make_masters.py\n"
            "  python scripts/make_variants.py\n"
            "  python scripts/precompute.py"
        )
        raise typer.Exit(code=1)

    started = time.perf_counter()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    hero = next(
        (r for r in index["runs"] if "apr_animates" in r["variant_id"]),
        next((r for r in index["runs"] if r["fail"]), None),
    )
    if hero is None:
        console.print("[yellow]no failing variant in the cache[/]")
        raise typer.Exit(code=1)

    run = json.loads((runs / f"{hero['variant_id']}.json").read_text(encoding="utf-8"))
    elapsed = time.perf_counter() - started

    console.print(f"[bold]{run['variant_id']}[/]")
    console.print(f"[dim]{run['label']['description']}[/]\n")
    for f in run["findings"]:
        if f["status"] == "fail":
            console.print(
                f"  [red]FAIL[/] {f['rule_id']} ({f['citation']}): {f['detail']}"
            )
    for f in run["findings"]:
        if f["status"] == "inconclusive":
            console.print(f"  [yellow]can't tell[/] {f['rule_id']}: {f['detail']}")
    console.print(f"\n[green]loaded from cache in {elapsed * 1000:.0f} ms[/] — no API key used")
    console.print(f"[dim]regions: {run['region_source']} · text: {run['text_source']}[/]")


if __name__ == "__main__":
    app()
