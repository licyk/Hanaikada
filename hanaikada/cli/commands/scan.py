"""scan: index roots in the foreground, or hand the scan to a running server."""

import json
import time
import urllib.error
import urllib.request
from typing import Annotated, Any

import typer

from hanaikada.cli.output import console, err_console, open_services


def _server_request(server: dict[str, Any], method: str, path: str, token: str | None, body: dict[str, Any] | None = None) -> Any:
    url = server["url"].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


def _via_server(server: dict[str, Any], token: str | None, body: dict[str, Any], wait: bool) -> None:
    status = _server_request(server, "POST", "/api/v1/index/scan", token, body)
    console.print(f"Queued on the running server at {server['url']} ({status['queued']} job(s) waiting)")
    if not wait:
        return
    while True:
        time.sleep(1.0)
        status = _server_request(server, "GET", "/api/v1/index/status", token)
        scanning = [r for r in status["roots"] if r["state"] in ("scanning", "queued")]
        for r in scanning:
            err_console.print(f"  {r['root_id']}: {r['files_indexed']} indexed, {r['files_seen']} seen, {r['files_failed']} failed", end="\r")
        if not status["running"] and status["queued"] == 0:
            break
    err_console.print()
    console.print("Scan finished")


def scan(
    root: Annotated[str | None, typer.Option(help="Only this root id")] = None,
    path: Annotated[str | None, typer.Option(help="Only this folder of the root, relative to it (needs --root)")] = None,
    full: Annotated[bool, typer.Option("--full", help="Re-read every file, ignoring modification times")] = False,
    reparse: Annotated[bool, typer.Option("--reparse", help="Run the parsers again over the stored metadata, without reading files")] = False,
    wait: Annotated[bool, typer.Option("--wait", help="When a server is running, wait for its scan to finish")] = False,
    local: Annotated[bool, typer.Option("--local", help="Scan in this process even when a server is running")] = False,
) -> None:
    """Index roots. When the web UI's server is running, the scan is queued there instead."""
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    from hanaikada.core.events.models import ScanCompletedEvent, ScanFailedEvent, ScanProgressEvent
    from hanaikada.core.index.models import ScanRequest
    from hanaikada.core.net.runtime_file import read_runtime_file

    if path and not root:
        raise typer.BadParameter("--path needs --root")
    request = ScanRequest(root_id=root, path=path, full=full, reparse=reparse)
    with open_services() as s:
        server = None if local else read_runtime_file(s.settings.data_dir)
        if server is not None:
            try:
                _via_server(server, s.settings.settings.server.access_token, request.model_dump(mode="json"), wait)
                return
            except (urllib.error.URLError, OSError) as e:
                err_console.print(f"[yellow]The server at {server.get('url')} did not answer ({e}); scanning here instead.[/yellow]")
        if reparse:
            with console.status("Re-parsing stored metadata…"):
                count = s.index.reparse(root)
            console.print(f"Re-parsed {count} images")
            return
        totals: dict[str, tuple[int, int, int]] = {}
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), console=err_console, transient=False) as progress:
            tasks: dict[str, Any] = {}

            def on_event(event: Any) -> None:
                if isinstance(event, ScanProgressEvent):
                    if event.root_id not in tasks:
                        tasks[event.root_id] = progress.add_task(event.root_id)
                    progress.update(
                        tasks[event.root_id],
                        description=f"{event.root_id}: {event.files_indexed} indexed · {event.files_seen} seen · {event.files_failed} failed · {event.folders_seen} folders  {event.current or ''}"[
                            :160
                        ],
                    )
                elif isinstance(event, ScanCompletedEvent):
                    totals[event.root_id] = (event.files_seen, event.files_indexed, event.files_failed)
                elif isinstance(event, ScanFailedEvent):
                    err_console.print(f"[red]Scan of {event.root_id} failed: {event.error}[/red]")

            unsubscribe = s.events.subscribe(on_event)
            try:
                s.index.scan_now(request)
            finally:
                unsubscribe()
        for root_id, (seen, indexed, failed) in totals.items():
            console.print(f"{root_id}: {seen} images seen, {indexed} (re)indexed, {failed} failed")
        if not totals and path:
            console.print("Folder scanned")
