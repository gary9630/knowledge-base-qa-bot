from __future__ import annotations

from pathlib import Path

import pytest

from scripts.seed_sample_docs import copy_sample_docs, main


def test_copy_sample_docs_copies_markdown_without_overwriting(tmp_path: Path) -> None:
    sample_dir = tmp_path / "sample-docs"
    docs_dir = tmp_path / "docs"
    nested_dir = sample_dir / "network"
    nested_dir.mkdir(parents=True)
    docs_dir.mkdir()

    root_markdown = sample_dir / "faq.md"
    nested_markdown = nested_dir / "guide.md"
    ignored_text = sample_dir / "notes.txt"
    existing_source = sample_dir / "existing.md"
    existing_target = docs_dir / "existing.md"

    root_markdown.write_text("# FAQ\n", encoding="utf-8")
    nested_markdown.write_text("# Guide\n", encoding="utf-8")
    ignored_text.write_text("not markdown\n", encoding="utf-8")
    existing_source.write_text("# Source version\n", encoding="utf-8")
    existing_target.write_text("# Keep local version\n", encoding="utf-8")

    copied_count = copy_sample_docs(sample_dir, docs_dir)

    assert copied_count == 2
    assert (docs_dir / "faq.md").read_text(encoding="utf-8") == "# FAQ\n"
    assert (docs_dir / "network" / "guide.md").read_text(encoding="utf-8") == "# Guide\n"
    assert not (docs_dir / "notes.txt").exists()
    assert existing_target.read_text(encoding="utf-8") == "# Keep local version\n"
    assert existing_source.read_text(encoding="utf-8") == "# Source version\n"


def test_cli_copies_explicit_paths_and_prints_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sample_dir = tmp_path / "sample-docs"
    docs_dir = tmp_path / "docs"
    sample_dir.mkdir()
    (sample_dir / "quickstart.md").write_text("# Quickstart\n", encoding="utf-8")

    exit_code = main(["--sample-dir", str(sample_dir), "--docs-dir", str(docs_dir)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Copied 1 Markdown file" in captured.out
    assert str(docs_dir) in captured.out
    assert (docs_dir / "quickstart.md").read_text(encoding="utf-8") == "# Quickstart\n"


def test_copy_sample_docs_rejects_symlinked_destination_parent(tmp_path: Path) -> None:
    sample_dir = tmp_path / "sample-docs"
    docs_dir = tmp_path / "docs"
    outside_dir = tmp_path / "outside"
    sample_dir.mkdir()
    docs_dir.mkdir()
    outside_dir.mkdir()
    (sample_dir / "nested").mkdir()
    (sample_dir / "nested" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (docs_dir / "nested").symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink directory"):
        copy_sample_docs(sample_dir, docs_dir)

    assert not (outside_dir / "guide.md").exists()


def test_copy_sample_docs_rejects_broken_destination_symlink(tmp_path: Path) -> None:
    sample_dir = tmp_path / "sample-docs"
    docs_dir = tmp_path / "docs"
    sample_dir.mkdir()
    docs_dir.mkdir()
    (sample_dir / "faq.md").write_text("# FAQ\n", encoding="utf-8")
    (docs_dir / "faq.md").symlink_to(tmp_path / "missing.md")

    with pytest.raises(ValueError, match="symlink"):
        copy_sample_docs(sample_dir, docs_dir)


def test_cli_returns_error_for_missing_sample_dir(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--sample-dir",
            str(tmp_path / "missing-samples"),
            "--docs-dir",
            str(tmp_path / "docs"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Error:" in captured.err
