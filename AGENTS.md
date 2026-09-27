# Hanaikada — notes for agents

The design record: what the code does, the rules it keeps and why. Add durable findings here, briefly.

## 1. Overview

A browser for images made with Stable Diffusion WebUI (A1111, Forge, Forge Classic, reForge,
SD.Next), ComfyUI and InvokeAI, plus NovelAI files. One core, two ends: a Typer command line
that does everything, and a Vue 3 web UI (Browse, Search, Tags, Stats, Settings, a viewer, a
compare view) served by the same Python process.

- `hanaikada` everywhere, env prefix `HANAIKADA_`, Python 3.10+, port 7867 (clear of SD Model
  Hub's 7865 and IIB's 7866), GPL-3.0 (reused code is GPL).
- Skeleton from SD Model Hub (settings, events, db, security, ports, CLI factory, embedding, the
  UI's theme, `ui/`, motion); indexing ideas from sd-webui-infinite-image-browsing (IIB).
- No network requests of its own. Out of scope: AI features, WebUI "send to", multi-user, NSFW
  detection (blur is by tag, `content.blur_tags`).

## 2. Layout and layers

```
hanaikada/
  core/        all logic; settings/ events/ db/ net/ metadata/ index/ library/, errors.py, context.py
  api/         FastAPI: routers/ (app_info settings library images search tags index), security,
               sockets, static, files, errors, deps. Thin.
  cli/         Typer: app.py (command tree), commands/, factory.py, output.py. Thin.
  webui/       the Vue project; dist/ is git-ignored and shipped as package data
  embed.py     HanaikadaServer / ImageRoot for running inside another application
scripts/       dev.py build_wheel.py generate_openapi.py extract_metadata_fixture.py run_parsers_over.py
tests/         core/ api/ cli/, fixtures/metadata/ (1×1 images carrying real chunks)
```

- **Layer rule** (`tests/core/test_architecture.py`): `core` imports only the standard library,
  `pydantic`, `PIL` (with `pillow_jxl`) and `piexif` — no web/CLI framework, `httpx`,
  `hanaikada.api` or `.cli`. Each operation is one core method on `Record` models; routes and
  commands only parse, call and shape, so the API's JSON equals the CLI's `--json`.
- `core/context.py:build_services()` builds everything once: the API keeps it on
  `app.state.services` (`ServicesDep`), the CLI opens and closes it per command
  (`open_services()`), tests pass `environ=`. No global locator.
- **Errors** are `core/errors.py` only, each with `code`/`http_status`/`exit_code`: `NotFound`
  404/2, `Conflict` (and `IndexBusy`) 409/3, `InvalidPath`, `Validation` (and `UnsupportedFile`)
  400/4, anything else 500/1. The API answers `{code, message, detail}`. A new failure is a new
  subclass.
- Logging is one Rich handler on **stderr**; stdout carries `--json` and `SERVER_READY url=…`.
- Keep two exports lazy: `core/index` (library ↔ index is a cycle) and the package's
  `HanaikadaServer`/`ImageRoot`/`serve` (so `hanaikada version` never imports FastAPI).

## 3. Commands and workflow

```bash
python scripts/dev.py check        # what CI runs: ruff, ty, pytest, vitest + vue-tsc, generated types — must pass
python scripts/dev.py dev          # API + Vite with hot reload
python scripts/dev.py test | corpus | typegen    # tests; every parser over local installs; regenerate schema.d.ts
python scripts/build_wheel.py      # web UI, then wheel and sdist
python scripts/run_parsers_over.py <folder>... --show-errors
python scripts/extract_metadata_fixture.py <image> <fixture.png|.jpg|.webp|.gif> [--compress]
```

- The web UI uses **bun**; TypeScript stays on 6.x (vue-tsc and openapi-typescript need its
  compiler API). Vite proxies to `HANAIKADA_BACKEND` (default `http://127.0.0.1:7867`).
- **API change → `typegen`** and commit `webui/src/api/schema.d.ts`; `check` fails until it matches git.
- **Packaging:** nothing in the build backend builds the UI, so a bare `python -m build` ships a
  wheel without it; use `scripts/build_wheel.py` (`--ci` only bundles; `--keep-web-dist`).
  `release.yml` runs on a `master` push changing `hanaikada/version.py`, a `v*` tag, or by hand.
- **A CLI command** is a plain function in `cli/commands/`, registered with name and help in
  `cli/app.py:get_app()` and added to `EXPECTED_TREE` in `tests/cli/test_cli.py`. Groups come from
  `typer_factory()` (eager `--debug` everywhere, alphabetical help). Import heavy modules inside
  the function. Private `typer._click` imports stay in `factory.py`; Typer has no upper pin.
- Commit and open PRs only when the user asks.

## 4. Conventions

- **Python:** ruff (line length 180), ty for 3.10 (no `typing.Self`; `tomli` fallback). Comments
  say why, not what.
- **Pydantic** v1 and v2: models crossing the API or CLI inherit `core/record.py:Record` (v2's API
  on v1; defaulted fields required in the schema so the TS types match). Unions there use strict
  types (`ExtraValue`): v1 coerces left to right and FastAPI re-validates, so `True` became `"True"`.
- **Settings:** defaults < `settings.toml` < env `HANAIKADA_<GROUP>__<FIELD>` (JSON when it
  parses, `null`/`none` → None) < host overrides; env and host values are never written back.
  Services follow edits through `on_change`. Secrets never leave the server (`access_token` →
  `access_token_configured`). Interface preferences are client state, not settings (§9).
- **Events** (`EventBase` subclasses with `__event_name__`) carry snapshots, never live objects;
  handlers run on the publishing thread; progress is throttled to 4/s at the source.
- **Database:** `MIGRATIONS` is append-only (`PRAGMA user_version`); one connection behind an
  `RLock`; multi-statement writes inside `db.transaction()`.
- **Vue:** `<script setup lang="ts">`, strict. Tests enforce `@/` imports, no hex colour outside
  `src/theme/`, `min-width: 0` on rows holding a file name, and matching locale keys. Views import
  only from `@/ui`, which alone imports `@material/web` and `@lucide/vue`. Shared constants of a
  component go in a `.ts` beside it (`<script setup>` cannot export).
- **Nothing from an image is rendered as HTML** (no Markdown, no DOMPurify): prompts, chunks and
  names are text.

## 5. Metadata

Container first (`containers.py`), then one parser per platform, chosen by `registry.py`. Raw
chunks are stored (truncated above `index.max_raw_bytes` and re-read on demand), so `scan
--reparse` applies a parser fix without re-reading files. A parser that raises leaves the
platform and a `parse_error`.

**Containers.**
- PNG is read by a chunk walker, not Pillow (Pillow skips chunks after `IDAT`, where APNG `comf`
  chunks sit). Pillow writes `tEXt` for Latin-1 text and `iTXt` otherwise; ComfyUI escapes
  non-ASCII, so none of the three platforms puts UTF-8 in `tEXt`. The walker still tries UTF-8
  first, for third-party writers. Decompressed text is capped at 64 MB; XMP is reported, not kept.
- Other formats open lazily in Pillow — always through `core/imaging.py`, which registers JPEG XL
  (`pillow-jxl-plugin` works only once imported); EXIF via `piexif`, a manual IFD walk as fallback;
  `UserComment` with `UNICODE` (BE, or LE by zero-byte position), `ASCII`, `JIS` or no prefix. The
  orientation swaps the reported size. A `<stem>.txt` sidecar is read only when the file has no
  generation text.

**Detection order:** InvokeAI (`invokeai_*`, legacy `sd-metadata`/`dream`/`invokeai`), ComfyUI
(`prompt` with `class_type` nodes, or `workflow`), NovelAI (`Software = NovelAI` + JSON `Comment`),
SD WebUI (`parameters`, or an infotext-shaped UserComment/GIF comment/`.txt`, or a
postprocessing-only UserComment). The WebUI copies an init image's chunks into its output, so
ComfyUI chunks next to a generation infotext (`parameters` with `Steps`) are the source image's:
the file is `sd-webui`, with a warning. An Extras output of a ComfyUI image (its graph plus
`postprocessing`) stays `comfyui`.

**SD WebUI (infotext).**
- PNG `parameters`; JPEG/WebP/AVIF/JXL only EXIF `UserComment` (`UNICODE\0` + UTF-16BE); GIF
  comment; `.heif/.tiff/.bmp` carry nothing. Extras output as JPEG/WebP holds only the
  postprocessing text. `parameters` is read before a UserComment (the WebUI itself prefers a
  non-empty UserComment; files with both are rare).
- Grammar: the WebUI's regex and the "at least three pairs on the last line" rule. Values with
  `,` `\n` `:` are JSON-quoted; booleans are `True`/`False`; key order varies (Forge writes
  `Model hash` before `Model`). No defaults are filled; `Clip skip`, `Noise Schedule` kept;
  `Key: value` lines after `Steps:` (Dynamic Prompts templates) stay apart from the prompt; old
  sampler names with a schedule (`DPM++ 2M Karras`) are split; Extras' `postprocessing` becomes an
  upscale pass, `mode = upscale`. Old forms: `Sampler: Undefined` is Euler + Simple; the pre-2023
  hires fix wrote the final size as `Size` and the base as `First pass size` (`0x0`: about
  512×512 in the final aspect, multiples of 64), with no `Hires` keys.
- `Model hash` is SHA-256[:10]; `Lora hashes` are 12 chars, keyed by the LoRA name with `:` and
  `,` removed; `Hashes` is a JSON object. Forge Classic omits `VAE`/`Hashes` and writes `TI:`
  names. img2img/inpaint is inferred from `Denoising strength` with `Mask blur`/`Inpaint area`.

**ComfyUI (API graph in `prompt`).**
- Node ids are strings (`"451:200"` inside subgraphs); a link is `[node_id, output]` and may point
  at a muted, absent node. Never key on `_meta.title` (localised).
- Pick the save node whose `filename_prefix` gives the file name (`<prefix>_NNNNN_` before a mere
  prefix match; server-side tokens `%width%`, `%year%`…`%second%`, `%batch_num%` match as
  digits, since the graph stores them unfilled), else a non-preview one with the most samplers
  upstream. Walk the image/latent chain to its samplers: first = base pass, later = `hires` (an
  upscale between), `refiner` (another model) or `sampler`; upscales after the last sampler =
  `upscale` passes. Prompts follow conditioning through combine/area/ControlNet nodes
  (output 0 positive, 1 negative). Links resolve through primitive and single-input pass-through
  nodes. Unmapped scalar inputs go to `extras` as `<class>#<id>.<input>`, at most 300.
- `family` from `CLIPLoader`/`DualCLIPLoader.type`; Flux `guidance` → `distilled_cfg`;
  `CLIPSetLastLayer` −n → clip skip n; img2img when the base latent comes from `VAEEncode`,
  inpaint from `SetLatentNoiseMask`/`InpaintModelConditioning`; version from
  `workflow.extra.frontendVersion`. Model names are relative paths; ComfyUI writes no hashes.
- A workflow-only file is rebuilt from positional widget tables for the core nodes. WebP/AVIF
  keep chunks as IFD0 `key:<json>` strings — split on the first `:`, don't trust tag numbers.
  Any `extra_pnginfo` key becomes its own chunk.

**InvokeAI.**
- `invokeai_metadata` (flat JSON; only `app_version` is guaranteed; absent = not set), else the
  graph's `core_metadata` node (fields through edges), else individual nodes. `invokeai_graph` is
  the source graph: batch values sit in primitive nodes reached by edges, so an encoder's own
  `prompt` may be `""`. A file may carry only `invokeai_workflow` (an editor export).
- Both model shapes: `{key, hash, name, base, type}` and 3.x `{model_name, base_model, model_type}`;
  `family` from `base`; `scheduler` split into sampler + `_k` → Karras; `strength` → denoise;
  `blake3:` hashes kept with their kind; `width`/`height` are the requested size. Legacy chunks:
  `dream` (<1.15), `sd-metadata` (1.15–2.3.5), `invokeai` (3.0 beta). Files are `<uuid>.png` with
  a WebP thumbnail within 256×256 (some forks use subfolders, `images.image_subfolder`).

**NovelAI:** `Description` (prompt) + `Comment` JSON, V4 caption objects included, mapped directly.

**Shared rules.**
- `sampler_norm` maps every vocabulary onto **ComfyUI's names** (`Euler a`, InvokeAI `euler_a` →
  `euler_ancestral`).
- Hashes are kept as written, never recomputed; WebUI SHA-256, InvokeAI BLAKE3 and ComfyUI's
  none don't match, so models are not matched across platforms.
- Seeds reach 2⁶⁴−1: exact in Python, two's complement above 2⁶³−1 in SQLite
  (`records.seed_to_db`, equality still works), strings in JSON beyond 2⁵³ (`BigInt`, Pydantic v2).

## 6. Index

SQLite `hanaikada.db` in the data directory: WAL, one migration, `images.dir` (one indexed query
per listing), `images.loras` (for the FTS delete trigger), `sampler_norm`, `family`,
`folders.parent` (an unchanged folder recurses into known children), a `client_state` table, and
a seeded `favorite` custom tag.

- **Text search:** FTS5 trigram (SQLite ≥ 3.34, detected; `/app/meta` reports `fts`) over prompt,
  negative, name, model and LoRAs as one quoted phrase; under three characters or without
  trigram it is `LIKE` over the same columns (`test_fts_and_like_give_the_same_rows`).
- **Tags:** prompt tokens split like IIB (commas, `BREAK`, newlines; weights and brackets
  stripped; `<lora:…>` pulled out; lower-cased) all become `prompt` tags, listed only once
  `index.prompt_tag_min_count` images share them. The negative prompt is searched, never
  tokenised. Counts are kept by triggers. Tag search is `HAVING COUNT(DISTINCT tag_id) = N` /
  `IN` / `NOT IN`. Custom tags are backed up to `tags-backup.json` on every change and restored as
  scans find their paths. InvokeAI boards, `starred`, `intermediate` become `board` tags, read
  from `invokeai.db` (`images`, `boards`, `board_images` only; read-only; `index.invokeai_read_db`).
- **Scanner:** one thread, a priority queue (requested files first, then folders, roots,
  re-parse, thumbnails). A folder is re-listed when its mtime differs, a file re-read when
  size or mtime differs; batches of 50. Unseen rows get `missing_since`, are hidden, and go after
  7 days. Watching polls folder mtimes every `index.watch_interval` s. The CLI never starts the
  thread: it scans in the foreground or hands the scan to a running server (`server.json`);
  without a running scanner nothing is queued. `POST /index/scan` is 409 only during a full
  rebuild of the same root. `index_changed` path lists stop at 200 (`more`).
- The mtime heuristic misses a file replaced within one clock tick; the live listing catches it.
- **Search** is keyset-paged over `(sort key, id)`; a cursor is refused by another sort; `random`
  hashes the id with a seed; a regex runs in Python over the other filters' rows, 500 at a time,
  up to 20,000 per request. `total` comes with the first page.

## 7. Library

A root is a folder plus a layout (`library/layouts.py`); the layout decides its **output
folders**. Only they, their ancestors and descendants are visible, and **files are listed and
served only inside output folders** (an install root never serves `config.json`). Dot entries,
`*.tmp`, `*.part`, `*.incomplete`, `Thumbs.db` are always hidden.

- `sd-webui`: each `outdir_*` of `config.json` (inside the root; defaults per key), else
  `outputs/` or `output/`, else the root; `log.csv` hidden. `comfyui`: `output/` (+ `temp/` with
  `index.include_comfyui_temp`). `invokeai`: `outputs/images/`; its `thumbnails/` is hidden, seeds
  thumbnails ≤ 256 and follows its image; `databases/invokeai.db` is found from any of those
  roots. `custom`: the folder itself. Detection: `config.json` with `outdir_txt2img_samples`,
  `invokeai.yaml`, `main.py` + `folder_paths.py`, `webui.py` + `modules/`. A generic folder name
  (`core`, `output`) takes its parent's name. A root with `index: false` is browsed, not scanned.
- **Listings are live:** `scandir` joined with the folder's rows; a file without a current row
  comes back `indexed: false` and is queued; a row without a file is marked missing. Folder covers
  (four newest) come from the index, else a capped scan, cached by mtime.
- **Operations** go through `safety.py` (`follow_symlinks`, default on, keeps a linked folder
  inside a root openable; otherwise escaping links are refused), never overwrite (error, numeric
  suffix or skip), carry `.txt`/`.json` sidecars (not a same-stem file that is itself an image),
  update the index in the same call (rows keep id and tags), drop thumbnails, publish events.
  Delete goes to the trash (`send2trash`, else `<data>/trash/`).
- **All folders** (`library.combined_view`, off by default): `list_combined()` returns every root's
  output folders, in root then layout order; a root that is its own output folder is one entry
  (`is_root`, path `""`) with no move, copy, rename or delete. A folder already reached through
  another entry is left out; colliding names become `name (root name)`; missing roots are
  reported. `*` stands for it in the UI and is refused as a root id. CLI: `ls --all-roots`.
- **Thumbnails:** WebP 128–768 (rounded up), shorter side = size, keyed by path, size, mtime,
  file size and quality (the ETag); `?t=<mtime_ns>` makes files and thumbnails cacheable for a
  year. Large PNGs decode once; locks stop a stampede; the cache is swept at start-up.

## 8. Server and API

- **Start-up:** the server binds its socket itself and hands it to uvicorn (no gap between check
  and serve): up to 20 ports upward on `EADDRINUSE`/`EACCES`, one with `strict_port`, 0 = any;
  `SO_EXCLUSIVEADDRUSE` on Windows, `SO_REUSEADDR` elsewhere. `webui` prints `SERVER_READY
  url=…` and writes `server.json` (host, port, url, pid) atomically; it is ignored when the pid
  is dead and removed only by its writer. Binding off loopback needs an access token.
- **Routes:** one router per resource under `/api/v1`, explicit `operation_id`, `def` routes for
  disk and database, event schemas and a `ServerEvents` map in OpenAPI
  (`scripts/generate_openapi.py` prints it offline). Anything holding a path is a query
  parameter. Uploads stream the raw body into a `.part` file (no multipart). `POST /library/open`
  is loopback-only (403 `not_local`). `POST /library/zip` streams; the browser saves it as a blob.
- **Security:** loopback by default. The `Host` check (anti DNS rebinding) applies when bound to
  loopback; state changes and socket handshakes need a matching `Origin`, or `Sec-Fetch-Site`
  `same-origin`/`none`/absent. Off loopback a token is required (bearer, `hanaikada_token` cookie
  or `?token=`, compared with `hmac.compare_digest`) for `/api/`, `/ws/`, `/openapi.json`,
  `/docs`; `/api/v1/app/health` is public. CORS only with `server.allowed_origins`.
- **Socket:** server → client only (`loop.call_soon_threadsafe` across threads); REST is the
  source of truth and the client refetches on reconnect.
- **Static UI** (`api/static.py`): `dist/` found through `hanaikada.webui.__path__` (checkout or
  wheel); missing `index.html` → API only, with a warning. `assets/*` are immutable for a year,
  the rest `no-cache`; the SPA fallback to `index.html` only for requests accepting `text/html`.
- **Embedding** (`embed.py`): `HanaikadaServer(...).start()/stop()` and `ImageRoot`. Pinned
  settings and locked roots can't be changed anywhere (`/app/meta` reports `roots_locked`). A
  host mounting `create_app(services)` itself enters `app.router.lifespan_context` and closes the
  services.

## 9. Web UI

Vue 3, Vite, TS 6, Vue Router (hash history), Pinia, TanStack Vue Query, `openapi-fetch` on the
generated `schema.d.ts`, socket.io-client, `@material/web` wrapped in `ui/`, Lucide icons.

- **No URL is compiled in:** Vite `base: './'`, and `api/baseUrl.ts` takes everything before the
  last `/assets/` of the running script, so one build works under any prefix (keep `assets/`).
  `<img>` URLs rely on the token cookie.
- **State:** server data in Vue Query; socket events invalidate it, debounced
  (`createInvalidator`); scan progress lives in `stores/scan.ts`. Interface preferences (theme,
  colour, contrast, language, last root, cell size, sort, info tab, shortcuts) are client state:
  localStorage `hanaikada:preferences`, mirrored to `client_state`. `index.html` reads that key to
  set the theme before the bundle — don't rename it. The search lives in the URL
  (`search/url.ts`); the last 20 searches are client state.
- **Pages keep their state** in memory only: `<KeepAlive>` in `App.vue`, each page's last address
  for the navigation (`router.ts:addressOf`), the shell's scroll offset per page, and
  `ui/useKeepScroll` for a page's own scrollers. A hidden page still sees route changes, so Browse
  and Search read and write the URL only while shown (`route.name`); `window` listeners stop on
  `onDeactivated`.
- **Browse:** `ui/VirtualGrid.vue` (own virtualiser; the keyboard model is
  `components/gridKeyboard.ts`, selection `stores/selection.ts`); two columns at least on a
  phone. Flatten is a search with `path_prefix`, not a folder walk. Grid folders carry their own
  root (`GridFolder.root_id`), which All folders (`COMBINED_VIEW_ID = '*'`) needs. Actions come
  from one list (`components/imageActions.ts`); dialogs open through `stores/dialogs.ts` and are
  mounted once in `App.vue`. The viewer walks the list it was opened from (`stores/viewer.ts`).
- **Video, audio, other files:** listed but not indexed (no metadata, favourites or tags). Grid
  videos are drawn by the browser from the file (`components/VideoThumb.vue`; the file route
  serves ranges): muted and looping while on screen when `prefs.videoAutoplay` (default on),
  else a still frame; paused under the viewer and for reduced motion. The viewer restarts a video
  or audio with sound (muted if the browser refuses), shows other files as a card with a download
  and a plain-text preview of small text files, and keeps pan/zoom gestures to images.
  `library.show_all_files` (off) lists every file type, still only inside output folders.
- **Narrow screens:** drawers (Browse's folders, Search's form) open below the toolbar, whose
  height is measured (`ui/useElementHeight`) because it wraps, so the button that opened a drawer
  can always close it; Browse's drawer also closes on its scrim, Escape, or a picked folder.
- **Theme:** every colour role comes from one source colour (`#a45a73`, `SchemeTonalSpot`,
  contrast 0/0.5/1); `tokens.css` colours are only a first-paint fallback. Tokens are Google's
  `--md-sys-*` plus our `--app-*` (e.g. `--app-width-*` `clamp()` widths); views use no literal
  colours, radii or durations.
- **Components:** targets ≥ 48 px; views never restyle a `ui/` component (add a variant there);
  `@material/web` is in maintenance mode, so a broken one is replaced inside `ui/`. `ui/Tabs.vue`
  re-sets the active tab after mount (`md-tabs` re-picks it). Charts are plain SVG.
- **Layout and motion:** window classes 600/840/1200/1600 (`theme/breakpoints.ts`); a bottom bar
  when compact, a rail otherwise. Motion only through `ui/motion/` (`TRANSITIONS`): fade-through
  between pages, shared-axis-x for tab content (`--axis-dir` on a positioned, x-clipped parent),
  drawer, sheet, scrim and others; reduced motion becomes a short fade.
- **Language:** `en`, `zh-CN`, or `auto` (default: `zh*` → Chinese, else English).

## 10. Testing

pytest runs offline (`live` and `corpus` deselected by default) and covers every layer: parsers
on fixture images, the index, library operations, the API, the CLI, embedding and the layer
rule. The corpus run passes when every local file gets a platform, none raises, and prompt, seed
and model are set wherever the format has them. vitest + vue-tsc cover the web rules, stores and
`ui/`. The suite also passes on Pydantic 1.10 with FastAPI 0.125 (big-seed JSON skipped).

## 11. Invariants

- `core` imports no web or CLI framework; the API and CLI stay thin.
- Nothing outside a root is read or written; nothing is overwritten silently.
- Text from an image is never rendered as HTML.
- A platform's own database is never written (`invokeai.db` is read-only).
- The index follows every operation in the same call.
- `schema.d.ts` is regenerated and committed with every API change.
- A parser failure never stops a scan; raw chunks are always kept.

## 12. Known gaps

- No metadata for video and audio (listed and playable only; WebUI video `description`, ComfyUI
  WebM/MP4/audio tags, InvokeAI-fork MP4 JSON sidecars), nor for Fooocus, SwarmUI or stealth-PNG
  files. No WebUI "send to".
- Watching polls mtimes (no inotify); a network share may need a longer interval.
- Big seeds beyond 2⁵³ reach the browser rounded under Pydantic v1.
- NovelAI and JPEG XL are tested on synthetic files only; FTS5 trigram unconfirmed on
  Windows Python; Windows untested overall.
- The web UI was driven in headless Chromium only (not Firefox or Safari; no desktop file drop).
- A zip download is assembled in browser memory before it is saved.
