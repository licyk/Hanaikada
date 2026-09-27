"""export, move, copy, rename, delete, mkdir, thumbs."""

import json
from pathlib import Path
from typing import Annotated

import typer

from hanaikada.cli.output import console, err_console, open_services, parse_path_arg, print_json

WHAT_KEYS = {
    "infotext": ("parameters", "UserComment", "comment", "sidecar:txt"),
    "workflow": ("workflow", "invokeai_workflow", "prompt", "invokeai_graph"),
}


def export(
    paths: Annotated[list[str], typer.Argument(help="Images: file paths or <root-id>:<path>")],
    what: Annotated[str, typer.Option(help="infotext, workflow or metadata")] = "metadata",
    to: Annotated[Path, typer.Option(help="Folder to write into", file_okay=False, resolve_path=True)] = Path("."),
) -> None:
    """Write an image's metadata out as files: its infotext as .txt, its workflow as .json, or the normalised record as .json."""
    from hanaikada.core.metadata import MetadataService

    if what not in ("infotext", "workflow", "metadata"):
        raise typer.BadParameter("--what must be infotext, workflow or metadata")
    to.mkdir(parents=True, exist_ok=True)
    service = MetadataService()
    written = 0
    with open_services() as s:
        for value in paths:
            path = Path(value).expanduser()
            if not path.is_file():
                root_id, rel = parse_path_arg(s, value)
                path = s.library.file_path(root_id, rel)
            parsed = service.read(path)
            if what == "metadata":
                content, suffix = parsed.info.model_dump_json(indent=2), ".metadata.json"
            else:
                key = next((k for k in WHAT_KEYS[what] if k in parsed.raw.chunks), None)
                if key is None:
                    err_console.print(f"[yellow]{path.name}: no {what}[/yellow]")
                    continue
                content = parsed.raw.chunks[key]
                if what == "workflow":
                    try:
                        content = json.dumps(json.loads(content), indent=2, ensure_ascii=False)
                    except ValueError:
                        pass
                suffix = ".txt" if what == "infotext" else ".workflow.json"
            target = to / f"{path.stem}{suffix}"
            target.write_text(content, encoding="utf-8")
            written += 1
            console.print(f"Wrote {target}")
    if not written:
        raise typer.Exit(1)


def _refs(s, values: list[str]):  # type: ignore[no-untyped-def]
    from hanaikada.core.library.models import PathRef

    refs = []
    for value in values:
        root_id, rel = parse_path_arg(s, value)
        refs.append(PathRef(root_id=root_id, path=rel))
    return refs


def _transfer(sources: list[str], destination: str, copy: bool, rename: bool, keep_going: bool, json_output: bool) -> None:
    from hanaikada.core.library.models import TransferRequest

    with open_services() as s:
        dest_root, dest_rel = parse_path_arg(s, destination)
        result = s.library.transfer(
            TransferRequest(items=_refs(s, sources), dest_root_id=dest_root, dest_dir=dest_rel, on_conflict="rename" if rename else "error", continue_on_error=keep_going),
            copy=copy,
        )
    if json_output:
        print_json(result)
        return
    for ref in result.paths:
        console.print(f"{'Copied' if copy else 'Moved'} to {ref.root_id}:{ref.path}")
    for error in result.errors:
        err_console.print(f"[red]{error.root_id}:{error.path}: {error.message}[/red]")
    if result.errors:
        raise typer.Exit(3)


def move(
    sources: Annotated[list[str], typer.Argument(help="Files or folders, then the destination folder last")],
    rename: Annotated[bool, typer.Option("--rename", help="Add a numeric suffix instead of failing when a name is taken")] = False,
    keep_going: Annotated[bool, typer.Option("--continue-on-error", help="Move what can be moved and report the rest")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Move images (with their sidecars) and folders into a folder of any root. The index follows."""
    if len(sources) < 2:
        raise typer.BadParameter("Give at least one source and a destination")
    _transfer(sources[:-1], sources[-1], False, rename, keep_going, json_output)


def copy(
    sources: Annotated[list[str], typer.Argument(help="Files or folders, then the destination folder last")],
    rename: Annotated[bool, typer.Option("--rename", help="Add a numeric suffix instead of failing when a name is taken")] = False,
    keep_going: Annotated[bool, typer.Option("--continue-on-error", help="Copy what can be copied and report the rest")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Copy images (with their sidecars) and folders into a folder of any root."""
    if len(sources) < 2:
        raise typer.BadParameter("Give at least one source and a destination")
    _transfer(sources[:-1], sources[-1], True, rename, keep_going, json_output)


def rename(
    path: Annotated[str, typer.Argument(help="File or folder: <root-id>:<path> or a path")],
    new_name: Annotated[str, typer.Argument(help="New name; sidecars follow an image's new stem")],
) -> None:
    """Rename an image with its sidecars, or a folder."""
    from hanaikada.core.library.models import RenameRequest

    with open_services() as s:
        root_id, rel = parse_path_arg(s, path)
        result = s.library.rename(RenameRequest(root_id=root_id, path=rel, new_name=new_name))
    console.print(f"Renamed to {result.paths[0].root_id}:{result.paths[0].path}")


def delete(
    paths: Annotated[list[str], typer.Argument(help="Files or folders: <root-id>:<path> or paths")],
    permanent: Annotated[bool, typer.Option("--permanent", help="Delete for good instead of moving to the trash")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation")] = False,
) -> None:
    """Delete images (with their sidecars) or folders. They go to the trash unless --permanent."""
    from hanaikada.core.library.models import DeleteRequest

    with open_services() as s:
        refs = _refs(s, paths)
        if not yes:
            where = "permanently" if permanent or not s.settings.settings.library.delete_to_trash else "to the trash"
            typer.confirm(f"Delete {len(refs)} item(s) {where}?", abort=True)
        result = s.library.delete(DeleteRequest(items=refs, permanent=permanent))
    for ref in result.paths:
        console.print(f"Deleted {ref.root_id}:{ref.path}")
    locations = sorted({t for t in result.trashed_to if t != "system"})
    if locations:
        console.print(f"Moved to {', '.join(locations)}")


def mkdir(path: Annotated[str, typer.Argument(help="New folder: <root-id>:<parent>/<name>")]) -> None:
    """Create a folder inside a root."""
    from hanaikada.core.library.models import FolderCreate

    with open_services() as s:
        root_id, rel = parse_path_arg(s, path)
        parent, _, name = rel.rpartition("/")
        created = s.library.create_folder(FolderCreate(root_id=root_id, path=parent, name=name))
    console.print(f"Created {created.root_id}:{created.path}")


def thumbs_generate(
    root: Annotated[str | None, typer.Option(help="Only this root id")] = None,
    size: Annotated[int, typer.Option(help="Thumbnail size in pixels: 128, 256, 384, 512 or 768")] = 256,
) -> None:
    """Pre-generate the thumbnail cache for indexed images."""
    from rich.progress import Progress

    from hanaikada.core.errors import HanaikadaError

    with open_services() as s:
        where, params = ("root_id = ? AND missing_since IS NULL", [root]) if root else ("missing_since IS NULL", [])
        rows = s.db.fetchall(f"SELECT root_id, rel_path FROM images WHERE {where}", params)
        failed = 0
        with Progress(console=err_console) as progress:
            task = progress.add_task("Thumbnails", total=len(rows))
            for row in rows:
                try:
                    s.library.thumbnail(row["root_id"], row["rel_path"], size)
                except (HanaikadaError, OSError, ValueError):
                    failed += 1
                except Exception:  # noqa: BLE001 - Pillow raises many types on broken images
                    failed += 1
                progress.advance(task)
    console.print(f"{len(rows) - failed} thumbnails ready, {failed} failed")


def thumbs_clear() -> None:
    """Delete the whole thumbnail cache."""
    with open_services() as s:
        removed = s.library.thumbnails.clear()
    console.print(f"Removed {removed} cached thumbnails")
