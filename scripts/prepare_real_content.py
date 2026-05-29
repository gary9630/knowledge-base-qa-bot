from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class PrepareSummary:
    files_discovered: int
    copied: int
    updated: int
    unchanged: int
    stale_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class StaleTargetMarkdownError(ValueError):
    pass


def prepare_real_content(
    source_dir: Path,
    docs_dir: Path,
    *,
    allow_stale: bool = False,
) -> PrepareSummary:
    source_root = _validated_source_root(source_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)
    docs_root = docs_dir.resolve(strict=True)
    if docs_dir.is_symlink() or docs_root.is_symlink():
        raise ValueError(f"Refusing to write into symlink docs directory: {docs_dir}")

    source_files = _source_markdown_files(source_root)
    source_relatives = {
        path.relative_to(source_root).as_posix()
        for path in source_files
    }
    stale_paths = _stale_target_markdown_paths(docs_root, source_relatives)
    if stale_paths and not allow_stale:
        joined = ", ".join(stale_paths[:10])
        raise StaleTargetMarkdownError(
            "Target docs directory contains stale Markdown files not present in "
            f"source; clean them manually or pass --allow-stale: {joined}"
        )

    copied = 0
    updated = 0
    unchanged = 0
    for source_path in source_files:
        relative_path = source_path.relative_to(source_root)
        target_path = docs_root / relative_path
        _validate_destination(target_path, docs_root)

        if target_path.exists() and not target_path.is_file():
            raise ValueError(f"Refusing to overwrite non-file destination: {target_path}")

        if target_path.exists() and source_path.read_bytes() == target_path.read_bytes():
            unchanged += 1
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            updated += 1
        else:
            copied += 1
        shutil.copy2(source_path, target_path)

    return PrepareSummary(
        files_discovered=len(source_files),
        copied=copied,
        updated=updated,
        unchanged=unchanged,
        stale_paths=tuple(stale_paths),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare runtime docs from private real course Markdown content."
    )
    parser.add_argument("--source-dir", type=Path, default=Path("course-materials-md"))
    parser.add_argument("--docs-dir", type=Path, default=Path("docs"))
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Report stale target Markdown without deleting or failing.",
    )
    namespace = parser.parse_args(argv)

    try:
        summary = prepare_real_content(
            namespace.source_dir,
            namespace.docs_dir,
            allow_stale=namespace.allow_stale,
        )
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "prepared",
                "source_dir": str(namespace.source_dir),
                "docs_dir": str(namespace.docs_dir),
                "summary": summary.to_dict(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _validated_source_root(source_dir: Path) -> Path:
    if source_dir.is_symlink():
        raise ValueError(f"Refusing to read symlink source directory: {source_dir}")
    source_root = source_dir.resolve(strict=True)
    if not source_root.is_dir():
        raise NotADirectoryError(f"Real content source path is not a directory: {source_dir}")
    return source_root


def _source_markdown_files(source_root: Path) -> tuple[Path, ...]:
    for path in sorted(source_root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Refusing to read source symlink: {path}")

    return tuple(
        sorted(
            (
                path
                for path in source_root.rglob("*")
                if path.is_file() and path.suffix.lower() in {".md", ".markdown"}
            ),
            key=lambda path: path.relative_to(source_root).as_posix(),
        )
    )


def _stale_target_markdown_paths(docs_root: Path, source_relatives: set[str]) -> tuple[str, ...]:
    stale_paths: list[str] = []
    for path in sorted(docs_root.rglob("*")):
        if path.is_symlink():
            if path.is_dir():
                raise ValueError(f"Refusing to inspect symlink directory: {path}")
            raise ValueError(f"Refusing to inspect target symlink: {path}")
        if not path.is_file() or path.suffix.lower() not in {".md", ".markdown"}:
            continue
        relative = path.relative_to(docs_root).as_posix()
        if relative not in source_relatives:
            stale_paths.append(relative)
    return tuple(stale_paths)


def _validate_destination(target_path: Path, docs_root: Path) -> None:
    if target_path.is_symlink():
        raise ValueError(f"Refusing to write through symlink destination: {target_path}")

    existing_parent = _nearest_existing_parent(target_path.parent, docs_root)
    if existing_parent.is_symlink():
        raise ValueError(f"Refusing to write through symlink directory: {existing_parent}")

    resolved_parent = existing_parent.resolve(strict=True)
    if not _is_relative_to(resolved_parent, docs_root):
        raise ValueError(f"Refusing to write outside docs directory: {target_path}")


def _nearest_existing_parent(path: Path, stop_at: Path) -> Path:
    current = path
    while not current.exists():
        if current == stop_at:
            return current
        current = current.parent
    return current


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
