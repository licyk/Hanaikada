"""tag list | add | remove | apply | unapply."""

from typing import Annotated

import typer

from hanaikada.cli.output import console, open_services, parse_path_arg, print_json, print_table

TYPE_HELP = "custom, prompt, lora, model, sampler, platform, size or board"


def tag_list(
    type_: Annotated[str | None, typer.Option("--type", help=TYPE_HELP)] = None,
    query: Annotated[str | None, typer.Option("--query", "-q", help="Only tags whose name contains this")] = None,
    limit: Annotated[int, typer.Option(min=1, max=5000)] = 100,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """List tags, most used first."""
    with open_services() as s:
        tags = s.index.list_tags(type_, query, limit)
    if json_output:
        print_json(tags)
        return
    print_table("Tags", ["ID", "Type", "Name", "Images", "Colour"], [(t.id, t.type, t.name, t.count, t.color or "") for t in tags])


def tag_add(
    name: Annotated[str, typer.Argument(help="Name of the new custom tag")],
    color: Annotated[str | None, typer.Option(help="Colour, e.g. #e91e63")] = None,
) -> None:
    """Create a custom tag."""
    from hanaikada.core.index.models import TagCreate

    with open_services() as s:
        tag = s.index.create_tag(TagCreate(name=name, color=color))
    console.print(f"Created tag {tag.name} (id {tag.id})")


def tag_remove(name: Annotated[str, typer.Argument(help="Name of a custom tag")]) -> None:
    """Delete a custom tag. Images keep their files; only the tag goes."""
    with open_services() as s:
        tag = s.index.find_tag(name, "custom")
        s.index.delete_tag(tag.id)
    console.print(f"Deleted tag {name}")


def _apply(name: str, paths: list[str], add: bool) -> None:
    from hanaikada.core.index.models import TagImagesRequest

    with open_services() as s:
        tag = s.index.find_tag(name, "custom")
        refs = [parse_path_arg(s, p) for p in paths]
        result = s.index.tag_images(tag.id, TagImagesRequest(paths=refs), add=add)
    console.print(f"{'Tagged' if add else 'Untagged'} {result.changed} image(s) {'with' if add else 'from'} {name}; {result.tag.count} in all")


def tag_apply(
    name: Annotated[str, typer.Argument(help="Custom tag")],
    paths: Annotated[list[str], typer.Argument(help="Images: <root-id>:<path> or file paths")],
) -> None:
    """Add a custom tag to images. Images not yet in the index are indexed first."""
    _apply(name, paths, True)


def tag_unapply(
    name: Annotated[str, typer.Argument(help="Custom tag")],
    paths: Annotated[list[str], typer.Argument(help="Images: <root-id>:<path> or file paths")],
) -> None:
    """Remove a custom tag from images."""
    _apply(name, paths, False)


def tag_show(
    target: Annotated[str, typer.Argument(help="An image: <root-id>:<path> or a file path")],
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Show every tag of one image."""
    with open_services() as s:
        root_id, rel = parse_path_arg(s, target)
        detail = s.index.by_path(root_id, rel)
    if json_output:
        print_json(detail.tags)
        return
    print_table(target, ["ID", "Type", "Name"], [(t.id, t.type, t.name) for t in detail.tags])
