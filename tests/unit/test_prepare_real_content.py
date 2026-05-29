from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.prepare_real_content import StaleTargetMarkdownError, main, prepare_real_content


def test_prepare_real_content_copies_updates_and_preserves_nested_markdown(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "course-materials-md"
    docs_dir = tmp_path / "runtime-docs"
    nested_dir = source_dir / "week-1"
    nested_dir.mkdir(parents=True)
    docs_dir.mkdir()

    (source_dir / "overview.md").write_text("# Overview\n", encoding="utf-8")
    (nested_dir / "cap.md").write_text("# CAP\n", encoding="utf-8")
    (source_dir / "ignore.txt").write_text("not markdown\n", encoding="utf-8")
    (docs_dir / "overview.md").write_text("# Old overview\n", encoding="utf-8")

    summary = prepare_real_content(source_dir, docs_dir)

    assert summary.files_discovered == 2
    assert summary.copied == 1
    assert summary.updated == 1
    assert summary.unchanged == 0
    assert summary.stale_paths == ()
    assert (docs_dir / "overview.md").read_text(encoding="utf-8") == "# Overview\n"
    assert (docs_dir / "week-1" / "cap.md").read_text(encoding="utf-8") == "# CAP\n"
    assert not (docs_dir / "ignore.txt").exists()


def test_prepare_real_content_rejects_stale_target_markdown(tmp_path: Path) -> None:
    source_dir = tmp_path / "course-materials-md"
    docs_dir = tmp_path / "runtime-docs"
    source_dir.mkdir()
    docs_dir.mkdir()
    (source_dir / "overview.md").write_text("# Overview\n", encoding="utf-8")
    (docs_dir / "stale.md").write_text("# Stale\n", encoding="utf-8")

    with pytest.raises(StaleTargetMarkdownError, match="stale.md"):
        prepare_real_content(source_dir, docs_dir)

    assert (docs_dir / "stale.md").read_text(encoding="utf-8") == "# Stale\n"


def test_prepare_real_content_can_report_stale_target_markdown_without_deleting(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "course-materials-md"
    docs_dir = tmp_path / "runtime-docs"
    source_dir.mkdir()
    docs_dir.mkdir()
    (source_dir / "overview.md").write_text("# Overview\n", encoding="utf-8")
    (docs_dir / "stale.md").write_text("# Stale\n", encoding="utf-8")

    summary = prepare_real_content(source_dir, docs_dir, allow_stale=True)

    assert summary.stale_paths == ("stale.md",)
    assert (docs_dir / "stale.md").read_text(encoding="utf-8") == "# Stale\n"


def test_prepare_real_content_rejects_source_symlinks(tmp_path: Path) -> None:
    source_dir = tmp_path / "course-materials-md"
    docs_dir = tmp_path / "runtime-docs"
    outside_file = tmp_path / "outside.md"
    source_dir.mkdir()
    docs_dir.mkdir()
    outside_file.write_text("# Outside\n", encoding="utf-8")
    (source_dir / "linked.md").symlink_to(outside_file)

    with pytest.raises(ValueError, match="source symlink"):
        prepare_real_content(source_dir, docs_dir)

    assert not (docs_dir / "linked.md").exists()


def test_prepare_real_content_rejects_destination_symlink_parent(tmp_path: Path) -> None:
    source_dir = tmp_path / "course-materials-md"
    docs_dir = tmp_path / "runtime-docs"
    outside_dir = tmp_path / "outside"
    source_dir.mkdir()
    docs_dir.mkdir()
    outside_dir.mkdir()
    (source_dir / "nested").mkdir()
    (source_dir / "nested" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (docs_dir / "nested").symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink directory"):
        prepare_real_content(source_dir, docs_dir)

    assert not (outside_dir / "guide.md").exists()


def test_prepare_real_content_cli_prints_json_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source_dir = tmp_path / "course-materials-md"
    docs_dir = tmp_path / "runtime-docs"
    source_dir.mkdir()
    (source_dir / "overview.md").write_text("# Overview\n", encoding="utf-8")

    exit_code = main(["--source-dir", str(source_dir), "--docs-dir", str(docs_dir)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "prepared"
    assert payload["summary"]["files_discovered"] == 1
    assert payload["summary"]["copied"] == 1
