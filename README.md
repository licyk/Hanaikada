<div align="center">

# Hanaikada 花筏

</div>

Browse, search and manage the images you made with **Stable Diffusion WebUI**, **ComfyUI**
and **InvokeAI**, from a web UI or the command line.

Hanaikada ("flower raft": petals drifting on water) reads the generation data each platform
writes into its images — the WebUI's infotext, ComfyUI's graph, InvokeAI's metadata, and
NovelAI's comment — turns it into one record, indexes it, and lets you:

- **Browse** your WebUI, ComfyUI and InvokeAI output folders (or any folder) in a fast,
  virtualised grid with folder covers, sorting, a flattened "everything below here" view, and
  filters by platform, model and sampler. New images appear as soon as they are written.
- **View** an image full screen with zoom, pan, a slideshow, a filmstrip, and an information
  panel: the prompt and every parameter, what changed from the previous image, every raw
  chunk (download a ComfyUI workflow as `.json` to drop it back into ComfyUI), and EXIF.
- **Search** by prompt text (a full-text trigram index), negative prompt, file name, model,
  LoRA, seed, steps, CFG, size, orientation, date and tags; the search lives in the URL.
- **Tag** images with your own tags and a favourite, alongside tags derived from the metadata
  (prompt words, LoRAs, models, samplers, sizes, InvokeAI boards).
- **Manage files**: move, copy, rename, delete (to the trash) and upload, with sidecar files
  following their image and the index following every change. Download a selection as a zip.
- **Compare** two images with a slider and a prompt diff, and see **statistics**: a
  contribution heatmap, images per month, and the models, samplers and LoRAs you use most.

The design, the conventions and the known gaps are in [AGENTS.md](AGENTS.md).

## Install

```bash
python -m pip install hanaikada
hanaikada --help
```

Python 3.10 or newer. The web UI is bundled into the package; you do not need Node.

Pydantic v1 and v2 are supported (v1 with Python 3.10–3.13 and `fastapi<0.126`).

## Start

```bash
hanaikada root add ~/stable-diffusion-webui     # the layout is detected: sd-webui
hanaikada root add ~/ComfyUI                     # comfyui
hanaikada root add ~/invokeai                    # invokeai
hanaikada webui                                  # scans in the background and opens the browser
```

A root can be an installation folder or one of its output folders. Hanaikada reads the WebUI's
`config.json` for its output folders, uses ComfyUI's `output/` (and `temp/` if you ask), and
InvokeAI's `outputs/images/` together with its thumbnails and, read-only, its boards.

## Command line

```text
hanaikada
├── webui                    start the server and open the web UI (--host --port --no-open --no-scan)
├── version | env
├── config  show | get | set | path
├── root    list | add <path> [--layout] [--name] [--no-index] | remove <id>
├── scan    [--root] [--path] [--full] [--reparse] [--wait]
├── ls      [<root:path>] --sort --asc --limit --recursive --all-roots
├── info    <file | root:path> [--raw]            parse one image; no index needed
├── search  [text] --in --regex --platform --model --sampler --seed --tag --any-tag --not-tag ...
├── tag     list | add | remove | apply | unapply | show
├── export  <paths...> --what infotext|workflow|metadata --to <dir>
├── move | copy <src...> <dst>    rename <path> <new-name>    delete <paths...>    mkdir <path>
└── thumbs  generate | clear
```

A path is `<root-id>:<relative path>` or a path on disk inside a root. Every listing accepts
`--json`, which prints the same records the API returns, and `--debug` works at every level.
While the web UI's server runs, `hanaikada scan` hands the scan to it.

```bash
hanaikada info ~/Downloads/ComfyUI_00042_.png            # what made this image?
hanaikada search "cherry blossoms" --platform comfyui --json
hanaikada search --model animagineXL --min-steps 30 --tag favorite
hanaikada export 1a2b3c4d:output/ComfyUI_00042_.png --what workflow --to ./workflows
```

Settings live in `settings.toml` in the data directory (`hanaikada config path`), and any of
them can be pinned by an environment variable such as `HANAIKADA_SERVER__PORT=8000`.

## Embedding

```python
from hanaikada import HanaikadaServer, ImageRoot

server = HanaikadaServer(
    data_dir="./hanaikada-data",
    image_roots=[ImageRoot("/srv/ComfyUI", name="ComfyUI")],
    lock_image_roots=True,        # the user cannot add, change or remove folders
    combined_view=True,           # offer "All folders" in Browse; shown locked in the settings
    port=0,                       # any free port
    api_prefix="/images",         # keep clear of the host's own routes
)
url = server.start()              # http://127.0.0.1:54123/images
server.stop()
```

## Security

The server listens on `127.0.0.1` by default and checks the `Host` and `Origin` of every
request. To listen on another address, set an access token first
(`hanaikada config set server.access_token <secret>`). Nothing outside the roots you add is
ever read or written, and nothing is overwritten.

## Development

```bash
pip install -e ".[dev]"
python scripts/dev.py web-install
python scripts/dev.py dev          # API and Vite together, with hot reload
python scripts/dev.py check        # what CI runs
```

## Licence

GPL-3.0.
