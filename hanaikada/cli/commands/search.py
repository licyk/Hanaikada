"""search: the index, from the command line."""

from typing import Annotated

import typer

from hanaikada.cli.output import console, human_size, open_services, parse_path_arg, print_json, print_table, short

IN_CHOICES = ("prompt", "negative", "name", "model", "loras")


def search(
    text: Annotated[str | None, typer.Argument(help="Substring to find in prompts, negative prompts, file names, models and LoRAs")] = None,
    in_: Annotated[list[str] | None, typer.Option("--in", help="Where to look: prompt, negative, name, model, loras (repeatable)")] = None,
    regex: Annotated[str | None, typer.Option(help="Regular expression over the same fields")] = None,
    root: Annotated[list[str] | None, typer.Option(help="Only these root ids (repeatable)")] = None,
    path: Annotated[str | None, typer.Option(help="Only this folder, recursively: <root-id>:<folder> or a folder path")] = None,
    platform: Annotated[list[str] | None, typer.Option(help="sd-webui, comfyui, invokeai, novelai or none (repeatable)")] = None,
    model: Annotated[list[str] | None, typer.Option(help="Model name (repeatable)")] = None,
    sampler: Annotated[list[str] | None, typer.Option(help="Sampler, in any platform's spelling (repeatable)")] = None,
    seed: Annotated[int | None, typer.Option(help="Exact seed")] = None,
    tag: Annotated[list[str] | None, typer.Option("--tag", help="Must have every one of these tags (repeatable)")] = None,
    any_tag: Annotated[list[str] | None, typer.Option("--any-tag", help="Must have at least one of these tags (repeatable)")] = None,
    not_tag: Annotated[list[str] | None, typer.Option("--not-tag", help="Must have none of these tags (repeatable)")] = None,
    min_steps: Annotated[int | None, typer.Option(help="At least this many steps")] = None,
    max_steps: Annotated[int | None, typer.Option(help="At most this many steps")] = None,
    sort: Annotated[str, typer.Option(help="mtime, ctime, name, size, seed or random")] = "mtime",
    asc: Annotated[bool, typer.Option("--asc", help="Ascending order")] = False,
    limit: Annotated[int, typer.Option(min=1, max=1000)] = 50,
    missing: Annotated[bool, typer.Option("--missing", help="Include files that are gone from disk")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Search the index."""
    from hanaikada.core.index.models import SearchQuery

    for choice in in_ or []:
        if choice not in IN_CHOICES:
            raise typer.BadParameter(f"--in must be one of {', '.join(IN_CHOICES)}")
    with open_services() as s:
        root_ids = list(root) if root else None
        prefix = None
        if path:
            path_root, prefix = parse_path_arg(s, path)
            root_ids = [path_root]

        def ids(names: list[str] | None) -> list[int]:
            return [s.index.find_tag(name).id for name in names or []]

        query = SearchQuery.model_validate(
            {
                "text": text,
                "text_in": in_ or None,
                "regex": regex,
                "root_ids": root_ids,
                "path_prefix": prefix,
                "platforms": platform or None,
                "models": model or None,
                "samplers": sampler or None,
                "seed": seed,
                "steps": (min_steps, max_steps) if min_steps is not None or max_steps is not None else None,
                "all_tags": ids(tag),
                "any_tags": ids(any_tag),
                "not_tags": ids(not_tag),
                "include_missing": missing,
                "sort": sort,
                "descending": not asc,
                "limit": limit,
            }
        )
        page = s.index.search(query)
    if json_output:
        print_json(page)
        return
    rows = [(f"{i.root_id}:{i.path}", i.platform or "", human_size(i.size), i.seed if i.seed is not None else "", short(i.model_name, 28), short(i.prompt, 60)) for i in page.items]
    total = f"{page.total} found" if page.total is not None else f"{len(page.items)} shown"
    print_table(f"Search — {total}", ["Path", "Platform", "Size", "Seed", "Model", "Prompt"], rows)
    if page.next_cursor:
        console.print("More results exist; raise --limit or narrow the search")
