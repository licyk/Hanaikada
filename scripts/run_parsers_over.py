"""Run every parser over a folder tree and report what they found: the corpus check.

    python scripts/run_parsers_over.py <folder>... [--json] [--show-errors] [--limit N]

For each image: the platform, whether it parsed, and whether prompt, seed and model came out. The
summary counts per platform; ``--show-errors`` lists every failure and every file whose platform
was detected but whose prompt, seed or model is empty. Nothing is written anywhere.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hanaikada.core.errors import UnsupportedFileError
from hanaikada.core.metadata import MetadataService
from hanaikada.core.settings.models import DEFAULT_IMAGE_EXTENSIONS


def iter_images(folders: list[Path], limit: int | None):
    count = 0
    for folder in folders:
        paths = [folder] if folder.is_file() else sorted(folder.rglob("*"))
        for path in paths:
            if path.is_file() and path.suffix.lower() in DEFAULT_IMAGE_EXTENSIONS:
                yield path
                count += 1
                if limit is not None and count >= limit:
                    return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/run_parsers_over.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="print one JSON line per file")
    parser.add_argument("--show-errors", action="store_true", help="list failures and files missing prompt, seed or model")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    service = MetadataService()
    platforms: Counter[str] = Counter()
    missing: Counter[str] = Counter()
    problems: list[str] = []
    unreadable = 0
    for path in iter_images(args.folders, args.limit):
        try:
            parsed = service.read(path)
        except UnsupportedFileError as e:
            unreadable += 1
            problems.append(f"UNREADABLE {path}: {e.message}")
            continue
        except Exception as e:  # noqa: BLE001 - the point is to find these
            unreadable += 1
            problems.append(f"CRASH {path}: {type(e).__name__}: {e}")
            continue
        info = parsed.info
        platforms[info.platform] += 1
        if parsed.error:
            problems.append(f"ERROR {info.platform} {path}: {parsed.error}")
        elif info.platform != "none":
            empty = [name for name, value in (("prompt", info.prompt), ("seed", info.seed), ("model", info.model)) if value is None]
            for name in empty:
                missing[f"{info.platform}:{name}"] += 1
            if empty:
                problems.append(f"MISSING {info.platform} {','.join(empty)} {path}")
        if args.json:
            print(
                json.dumps(
                    {
                        "path": str(path),
                        "platform": info.platform,
                        "error": parsed.error,
                        "prompt": bool(info.prompt),
                        "seed": info.seed,
                        "model": info.model.name if info.model else None,
                    },
                    ensure_ascii=False,
                )
            )

    total = sum(platforms.values())
    print(f"\n{total} images parsed, {unreadable} unreadable", file=sys.stderr)
    for name, count in platforms.most_common():
        print(f"  {name:<10} {count}", file=sys.stderr)
    errors = sum(1 for p in problems if p.startswith(("ERROR", "CRASH")))
    print(f"  parse errors: {errors}", file=sys.stderr)
    for key, count in sorted(missing.items()):
        print(f"  missing {key}: {count}", file=sys.stderr)
    if args.show_errors:
        for line in problems:
            print(line, file=sys.stderr)
    return 1 if any(p.startswith("CRASH") for p in problems) else 0


if __name__ == "__main__":
    sys.exit(main())
