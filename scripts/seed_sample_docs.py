from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path


def copy_sample_docs(sample_dir: Path, docs_dir: Path) -> int:
    """Copy sample Markdown files into docs_dir without deleting or overwriting files."""
    sample_root = sample_dir.resolve(strict=True)
    if not sample_root.is_dir():
        raise NotADirectoryError(f"Sample docs path is not a directory: {sample_dir}")

    docs_dir.mkdir(parents=True, exist_ok=True)
    docs_root = docs_dir.resolve(strict=True)
    copied_count = 0

    for source_path in _markdown_files(sample_root):
        relative_path = source_path.relative_to(sample_root)
        target_path = docs_root / relative_path
        _validate_destination(target_path, docs_root)
        if target_path.exists():
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        copied_count += 1

    return copied_count


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed docs/ with Markdown files from sample-docs/ without overwriting files."
    )
    parser.add_argument("--sample-dir", type=Path, default=Path("sample-docs"))
    parser.add_argument("--docs-dir", type=Path, default=Path("docs"))
    namespace = parser.parse_args(argv)

    sample_dir: Path = namespace.sample_dir
    docs_dir: Path = namespace.docs_dir

    try:
        copied_count = copy_sample_docs(sample_dir, docs_dir)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    noun = "file" if copied_count == 1 else "files"
    print(f"Copied {copied_count} Markdown {noun} from {sample_dir} to {docs_dir}.")
    return 0


def _markdown_files(sample_root: Path) -> Iterable[Path]:
    candidates = (path for path in sample_root.rglob("*") if path.suffix.lower() == ".md")
    return sorted(
        (path for path in candidates if path.is_file() and not path.is_symlink()),
        key=lambda path: path.relative_to(sample_root).as_posix(),
    )


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
