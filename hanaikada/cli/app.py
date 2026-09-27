"""Entry point: ``get_app()`` registers every command; ``main()`` runs it with uniform error handling."""

import sys
import traceback

import typer
from typer import Abort, Exit

from hanaikada.cli.commands.browse import info, ls
from hanaikada.cli.commands.config import config_get, config_path, config_set, config_show
from hanaikada.cli.commands.files import copy, delete, export, mkdir, move, rename, thumbs_clear, thumbs_generate
from hanaikada.cli.commands.root import root_add, root_list, root_remove
from hanaikada.cli.commands.scan import scan
from hanaikada.cli.commands.search import search
from hanaikada.cli.commands.system import env, version
from hanaikada.cli.commands.tag import tag_add, tag_apply, tag_list, tag_remove, tag_show, tag_unapply
from hanaikada.cli.commands.webui import webui
from hanaikada.cli.factory import ClickException, typer_factory
from hanaikada.logger import setup_logging

logger = setup_logging()


def get_app() -> typer.Typer:
    """Build the Hanaikada command line. Every command is registered here, and nowhere else."""
    app = typer_factory("Browse, search and manage images made with Stable Diffusion WebUI, ComfyUI and InvokeAI")

    app.command(help="Start the server and open the web UI", name="webui")(webui)
    app.command(help="Show the version of Hanaikada and its main components", name="version")(version)
    app.command(help="List the environment variables Hanaikada reads", name="env")(env)
    app.command(help="Index roots, in the foreground or on the running server", name="scan")(scan)
    app.command(help="List a folder with each image's platform, seed, model and prompt", name="ls")(ls)
    app.command(help="Parse one image and print how it was made; no index needed", name="info")(info)
    app.command(help="Search the index", name="search")(search)
    app.command(help="Write an image's infotext, workflow or metadata out as files", name="export")(export)
    app.command(help="Move images with their sidecars, and folders; the index follows", name="move")(move)
    app.command(help="Copy images with their sidecars, and folders", name="copy")(copy)
    app.command(help="Rename an image with its sidecars, or a folder", name="rename")(rename)
    app.command(help="Delete images with their sidecars, or folders (to the trash by default)", name="delete")(delete)
    app.command(help="Create a folder inside a root", name="mkdir")(mkdir)

    config_cli = typer_factory(help="Show and change settings")
    config_cli.command(help="Show the effective settings", name="show")(config_show)
    config_cli.command(help="Print one setting", name="get")(config_get)
    config_cli.command(help="Change one setting and save it", name="set")(config_set)
    config_cli.command(help="Print the path of the settings file", name="path")(config_path)
    app.add_typer(config_cli, name="config")

    root_cli = typer_factory(help="Folders of images: WebUI, ComfyUI and InvokeAI installs, or any folder")
    root_cli.command(help="List roots", name="list")(root_list)
    root_cli.command(help="Add a root; the layout is detected unless given", name="add")(root_add)
    root_cli.command(help="Forget a root and its index rows; files are not touched", name="remove")(root_remove)
    app.add_typer(root_cli, name="root")

    tag_cli = typer_factory(help="Tags: custom tags you apply, and tags derived from metadata")
    tag_cli.command(help="List tags, most used first", name="list")(tag_list)
    tag_cli.command(help="Create a custom tag", name="add")(tag_add)
    tag_cli.command(help="Delete a custom tag", name="remove")(tag_remove)
    tag_cli.command(help="Add a custom tag to images", name="apply")(tag_apply)
    tag_cli.command(help="Remove a custom tag from images", name="unapply")(tag_unapply)
    tag_cli.command(help="Show every tag of one image", name="show")(tag_show)
    app.add_typer(tag_cli, name="tag")

    thumbs_cli = typer_factory(help="The thumbnail cache")
    thumbs_cli.command(help="Pre-generate thumbnails for indexed images", name="generate")(thumbs_generate)
    thumbs_cli.command(help="Delete the whole thumbnail cache", name="clear")(thumbs_clear)
    app.add_typer(thumbs_cli, name="thumbs")

    return app


def main() -> None:
    """Run the command line."""
    from hanaikada.core.errors import HanaikadaError

    try:
        get_app()()
    except Exit as e:
        sys.exit(e.exit_code)
    except Abort:
        logger.error("Cancelled")
        sys.exit(1)
    except ClickException as e:
        e.show()
        sys.exit(e.exit_code)
    except HanaikadaError as e:
        logger.error("%s", e.message)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        logger.error("Interrupted")
        sys.exit(130)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        logger.error("Command failed: %s", e)
        sys.exit(1)
