"""version, env."""

import os
import platform
import sqlite3
from importlib import metadata
from typing import Annotated

import typer

from hanaikada.cli.output import print_json, print_table
from hanaikada.version import VERSION

COMPONENTS = ("fastapi", "uvicorn", "python-socketio", "pydantic", "typer", "Pillow", "piexif", "pillow-jxl-plugin")

ENV_VARS = {
    "HANAIKADA_DATA_DIR": "Data directory holding settings.toml, the database and the thumbnail cache",
    "HANAIKADA_LOG_LEVEL": "Log level: DEBUG, INFO, WARNING or ERROR",
    "HANAIKADA_<GROUP>__<FIELD>": "Override one setting, e.g. HANAIKADA_SERVER__PORT=8000 or HANAIKADA_INDEX__WATCH_INTERVAL=0",
}


def version(
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """Show the version of Hanaikada and its main components."""
    from hanaikada.core.db.database import fts_available

    components: dict[str, str | None] = {}
    for name in COMPONENTS:
        try:
            components[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            components[name] = None
    sqlite = {"version": sqlite3.sqlite_version, "fts_trigram": fts_available()}
    if json_output:
        print_json({"hanaikada": VERSION, "python": platform.python_version(), "sqlite": sqlite, "components": components})
        return
    rows = [
        ("hanaikada", VERSION),
        ("python", platform.python_version()),
        ("sqlite", f"{sqlite['version']} ({'full-text search' if sqlite['fts_trigram'] else 'no trigram FTS: LIKE search'})"),
        *((k, v or "not installed") for k, v in components.items()),
    ]
    print_table(None, ["Component", "Version"], rows)


def env(
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """List the environment variables Hanaikada reads, and those currently set."""
    in_use = {k: ("***" if "TOKEN" in k else v) for k, v in sorted(os.environ.items()) if k.startswith("HANAIKADA_")}
    if json_output:
        print_json({"known": ENV_VARS, "set": in_use})
        return
    print_table("Environment variables", ["Name", "Meaning"], ENV_VARS.items())
    if in_use:
        print_table("Set now", ["Name", "Value"], in_use.items())
