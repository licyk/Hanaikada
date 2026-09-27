"""ls, info: browse a root, and read one file's metadata."""

from pathlib import Path
from typing import Annotated, Any

import typer

from hanaikada.cli.output import console, human_size, open_services, parse_path_arg, print_json, print_table, short

SORT_HELP = "Sort by name, mtime, ctime, size or random"


def _row(entry: Any) -> tuple[Any, ...]:
    image = entry.image
    return (
        entry.name,
        (image.platform if image and image.platform != "none" else "") if entry.kind == "image" else entry.kind,
        human_size(entry.size),
        image.seed if image else "",
        short(image.model_name, 28) if image else "",
        short(image.prompt, 60) if image else ("(not indexed)" if entry.kind == "image" else ""),
    )


def ls(
    location: Annotated[str | None, typer.Argument(help="<root-id>:<folder>, or a folder path inside a root; no argument lists the roots")] = None,
    sort: Annotated[str, typer.Option(help=SORT_HELP)] = "mtime",
    desc: Annotated[bool, typer.Option("--desc/--asc", help="Descending or ascending")] = True,
    limit: Annotated[int, typer.Option(min=1, help="At most this many files")] = 200,
    recursive: Annotated[bool, typer.Option("--recursive", "-r", help="Include subfolders")] = False,
    all_roots: Annotated[bool, typer.Option("--all-roots", help="The output folders of every root side by side, as the web UI's All folders")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """List a folder: subfolders, then images with their platform, seed, model and prompt."""
    if sort not in ("name", "mtime", "ctime", "size", "random"):
        raise typer.BadParameter(SORT_HELP)
    if all_roots:
        if location is not None or recursive:
            raise typer.BadParameter("--all-roots lists every root's output folders; it takes no location and no --recursive")
        with open_services() as s:
            combined = s.library.list_combined()
        if json_output:
            print_json(combined)
            return
        rows = [(f"{f.display_name}/", f.label or "", "whole root" if f.is_root else "output folder", f"{f.root_id}:{f.path}") for f in combined.folders]
        print_table("All folders", ["Name", "Label", "Shows", "Open with"], rows)
        if combined.missing_roots:
            console.print(f"Missing or unreadable roots: {', '.join(combined.missing_roots)}")
        return
    with open_services() as s:
        if location is None:
            roots = s.library.list_roots()
            if json_output:
                print_json(roots)
            else:
                print_table("Roots (pass <root-id>:<folder>)", ["ID", "Name", "Layout", "Path"], [(r.id, r.name, r.layout, r.path) for r in roots])
            return
        root_id, rel = parse_path_arg(s, location)
        if not recursive:
            listing = s.library.list_entries(root_id, rel, sort=sort, descending=desc, limit=limit)  # type: ignore[arg-type]
            if json_output:
                print_json(listing)
                return
            if listing.folders:
                print_table(
                    None,
                    ["Folder", "Label", "Modified"],
                    [(f.name + "/", f.label or "", f.mtime.astimezone().strftime("%Y-%m-%d %H:%M") if f.mtime else "") for f in listing.folders],
                )
            print_table(f"{root_id}:{listing.path or '/'} — {listing.total_files} files", ["Name", "Platform", "Size", "Seed", "Model", "Prompt"], [_row(e) for e in listing.files])
            if listing.next_cursor:
                console.print(f"… {listing.total_files - len(listing.files)} more; raise --limit to see them")
            return
        entries: list[Any] = []
        stack = [rel]
        while stack and len(entries) < limit:
            current = stack.pop()
            listing = s.library.list_entries(root_id, current, sort=sort, descending=desc, limit=limit - len(entries))  # type: ignore[arg-type]
            entries.extend(listing.files)
            stack.extend(reversed([f.path for f in listing.folders]))
        if json_output:
            print_json(entries)
            return
        print_table(f"{root_id}:{rel or '/'} (recursive)", ["Path", "Platform", "Size", "Seed", "Model", "Prompt"], [(e.path, *_row(e)[1:]) for e in entries])


def _info_rows(info: Any) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [("platform", info.platform + (f" {info.platform_version}" if info.platform_version else ""))]

    def add(label: str, value: Any) -> None:
        if value not in (None, "", []):
            rows.append((label, str(value)))

    add("mode", info.mode)
    add("family", info.family)
    add("prompt", info.prompt)
    add("negative prompt", info.negative_prompt)
    add("seed", info.seed)
    add("steps", info.steps)
    add("cfg scale", info.cfg_scale)
    add("distilled cfg", info.distilled_cfg)
    sampler = " / ".join(v for v in (info.sampler, info.scheduler) if v)
    add("sampler", sampler + (f"  ({info.sampler_norm})" if info.sampler_norm and info.sampler_norm != info.sampler else ""))
    add("size", f"{info.width}x{info.height}" if info.width and info.height else None)
    if info.model:
        add("model", info.model.name + (f"  [{info.model.hash_kind or 'hash'} {info.model.hash}]" if info.model.hash else ""))
    if info.vae:
        add("vae", info.vae.name)
    for lora in info.loras:
        weights = "/".join(f"{w:g}" for w in (lora.weight, lora.weight_clip) if w is not None)
        add("lora", f"{lora.name}{'  ' + weights if weights else ''}{'  [' + lora.hash + ']' if lora.hash else ''}")
    add("clip skip", info.clip_skip)
    add("denoise", info.denoise)
    for step in info.passes:
        parts = [f"{k}={v}" for k, v in step.model_dump(exclude_none=True).items() if k not in ("kind", "model")]
        if step.model:
            parts.append(f"model={step.model.name}")
        add(f"pass: {step.kind}", ", ".join(parts))
    for control in info.controls:
        add("control", ", ".join(f"{k}={v}" for k, v in control.items() if k != "node"))
    for key, value in info.extras.items():
        add(f"· {key}", value)
    add("sources", ", ".join(info.sources))
    for warning in info.warnings:
        add("warning", warning)
    return rows


def info(
    target: Annotated[str, typer.Argument(help="An image file anywhere, or <root-id>:<path>")],
    raw: Annotated[bool, typer.Option("--raw", help="Also print every text chunk and EXIF entry")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Parse one image and print what it says about how it was made. No index or root is needed for a file path."""
    from hanaikada.core.metadata import MetadataService
    from hanaikada.core.metadata.views import parse_result

    path = Path(target).expanduser()
    if path.is_file():
        parsed = MetadataService().read(path)
    else:
        with open_services() as s:
            root_id, rel = parse_path_arg(s, target)
            parsed = s.metadata.read(s.library.file_path(root_id, rel))
    result = parse_result(parsed)
    if json_output:
        print_json(result)
        return
    print_table(None, ["Field", "Value"], _info_rows(result.info))
    if result.error:
        console.print(f"[red]Parser error: {result.error}[/red]")
    if raw:
        view = result.raw
        print_table(
            "File",
            ["Field", "Value"],
            [("format", view.format or ""), ("size", f"{view.width}x{view.height}"), ("mode", view.mode or ""), ("frames", view.frames), *view.info.items()],
        )
        for chunk in view.chunks:
            console.rule(f"{chunk.key}  ({chunk.source or '?'})")
            console.print(chunk.value, markup=False, highlight=False)
