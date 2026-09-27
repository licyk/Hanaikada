"""root list | add | remove."""

from pathlib import Path
from typing import Annotated

import typer

from hanaikada.cli.output import console, open_services, print_json, print_table

LAYOUT_HELP = "Layout: auto (detect), sd-webui, comfyui, invokeai or custom"


def root_list(json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False) -> None:
    """List roots."""
    with open_services() as s:
        roots = s.library.list_roots()
        summary = {r.root_id: r for r in s.index.roots_summary()}
    if json_output:
        print_json(roots)
        return
    rows = []
    for r in roots:
        info = summary.get(r.id)
        flags = ", ".join(f for f, on in (("disabled", not r.enabled), ("browse only", not r.index), ("MISSING", not r.exists)) if on)
        rows.append((r.id, r.name, r.layout, r.path, ", ".join(r.outputs) or "-", info.images if info else 0, flags))
    print_table("Roots", ["ID", "Name", "Layout", "Path", "Output folders", "Images", "Notes"], rows)


def root_add(
    path: Annotated[Path, typer.Argument(help="Folder to add", exists=True, file_okay=False, resolve_path=True)],
    layout: Annotated[str, typer.Option(help=LAYOUT_HELP)] = "auto",
    name: Annotated[str | None, typer.Option(help="Display name")] = None,
    no_index: Annotated[bool, typer.Option("--no-index", help="Browse only: do not index this root in the background")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Add a root. With --layout auto the layout is detected from the folder."""
    from hanaikada.core.library.models import RootCreate

    with open_services() as s:
        if layout == "auto":
            suggestion = s.library.suggest_layout(str(path))
            if not json_output:
                console.print(f"Detected layout [bold]{suggestion.layout}[/bold]: {suggestion.reason}")
        root = s.library.add_root(RootCreate.model_validate({"name": name, "path": str(path), "layout": layout, "index": not no_index}))
    if json_output:
        print_json(root)
        return
    console.print(f"Added root [bold]{root.id}[/bold] ({root.layout}): {root.path}")
    if root.outputs:
        console.print(f"Output folders: {', '.join(o or '(the root itself)' for o in root.outputs)}")
    if root.index:
        console.print(f"Index it now with: hanaikada scan --root {root.id}")


def root_remove(root_id: Annotated[str, typer.Argument(help="Root id")]) -> None:
    """Forget a root and its index rows. Files are not touched."""
    with open_services() as s:
        s.library.remove_root(root_id)
    console.print(f"Removed root {root_id}")
