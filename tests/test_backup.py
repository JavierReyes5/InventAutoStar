"""
Tests for create_backup and cleanup_backups.
"""
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from update import BackupError, cleanup_backups, create_backup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _backup_filename(dt: datetime) -> str:
    """Return a backup filename matching the expected pattern."""
    return f"inventario_autostar_{dt.strftime('%Y%m%d_%H%M%S')}.html"


def _write_backup(backup_dir: Path, dt: datetime, content: str = "<html>backup</html>") -> Path:
    """Write a fake backup file with the given timestamp name."""
    p = backup_dir / _backup_filename(dt)
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# create_backup — naming and return value
# ---------------------------------------------------------------------------


def test_create_backup_creates_file(sample_html_output_path, backup_dir):
    backup_path = create_backup(sample_html_output_path, backup_dir)
    assert backup_path.exists()


def test_create_backup_returns_path_object(sample_html_output_path, backup_dir):
    backup_path = create_backup(sample_html_output_path, backup_dir)
    assert isinstance(backup_path, Path)


def test_create_backup_filename_pattern(sample_html_output_path, backup_dir):
    backup_path = create_backup(sample_html_output_path, backup_dir)
    pattern = r"^inventario_autostar_\d{8}_\d{6}\.html$"
    assert re.match(pattern, backup_path.name), f"Unexpected name: {backup_path.name}"


def test_create_backup_file_in_backup_dir(sample_html_output_path, backup_dir):
    backup_path = create_backup(sample_html_output_path, backup_dir)
    assert backup_path.parent == backup_dir


def test_create_backup_content_matches_original(sample_html_output_path, backup_dir):
    original_content = sample_html_output_path.read_bytes()
    backup_path = create_backup(sample_html_output_path, backup_dir)
    assert backup_path.read_bytes() == original_content


def test_create_backup_size_matches_original(sample_html_output_path, backup_dir):
    orig_size = sample_html_output_path.stat().st_size
    backup_path = create_backup(sample_html_output_path, backup_dir)
    assert backup_path.stat().st_size == orig_size


# ---------------------------------------------------------------------------
# create_backup — directory creation
# ---------------------------------------------------------------------------


def test_create_backup_creates_dir_if_not_exists(tmp_path, sample_html_output_path):
    new_backup_dir = tmp_path / "new_backups" / "nested"
    assert not new_backup_dir.exists()
    backup_path = create_backup(sample_html_output_path, new_backup_dir)
    assert new_backup_dir.exists()
    assert backup_path.exists()


# ---------------------------------------------------------------------------
# create_backup — integrity failure (simulated)
# ---------------------------------------------------------------------------


def test_create_backup_integrity_check_passes_for_valid_file(sample_html_output_path, backup_dir):
    """No BackupError should be raised when file is copied correctly."""
    backup_path = create_backup(sample_html_output_path, backup_dir)
    assert backup_path.stat().st_size == sample_html_output_path.stat().st_size


# ---------------------------------------------------------------------------
# cleanup_backups — files older than 7 days deleted
# ---------------------------------------------------------------------------


def test_cleanup_removes_old_backups(backup_dir):
    old_dt = datetime.now() - timedelta(days=8)
    old_file = _write_backup(backup_dir, old_dt)
    cleanup_backups(backup_dir)
    assert not old_file.exists()


def test_cleanup_removes_exactly_7_days_old(backup_dir):
    """Files strictly older than 7 days (before 00:00 cutoff) are removed."""
    # 7 days and 1 hour ago — before the cutoff
    old_dt = datetime.now() - timedelta(days=7, hours=1)
    old_file = _write_backup(backup_dir, old_dt)
    cleanup_backups(backup_dir)
    assert not old_file.exists()


def test_cleanup_removes_multiple_old_backups(backup_dir):
    old_dates = [
        datetime.now() - timedelta(days=10),
        datetime.now() - timedelta(days=20),
        datetime.now() - timedelta(days=8),
    ]
    old_files = [_write_backup(backup_dir, dt) for dt in old_dates]
    cleanup_backups(backup_dir)
    for f in old_files:
        assert not f.exists()


# ---------------------------------------------------------------------------
# cleanup_backups — files within 7 days kept
# ---------------------------------------------------------------------------


def test_cleanup_keeps_recent_backups(backup_dir):
    recent_dt = datetime.now() - timedelta(days=3)
    recent_file = _write_backup(backup_dir, recent_dt)
    cleanup_backups(backup_dir)
    assert recent_file.exists()


def test_cleanup_keeps_today_backup(backup_dir):
    today_dt = datetime.now()
    today_file = _write_backup(backup_dir, today_dt)
    cleanup_backups(backup_dir)
    assert today_file.exists()


def test_cleanup_keeps_exactly_at_cutoff_boundary(backup_dir):
    """Files at exactly the 7-day mark (today - 7 days at 00:00:00) should be kept."""
    cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
    boundary_file = _write_backup(backup_dir, cutoff)
    cleanup_backups(backup_dir)
    assert boundary_file.exists()


def test_cleanup_mixed_old_and_recent(backup_dir):
    old_dt = datetime.now() - timedelta(days=15)
    recent_dt = datetime.now() - timedelta(days=2)
    old_file = _write_backup(backup_dir, old_dt, content="<html>old</html>")
    recent_file = _write_backup(backup_dir, recent_dt, content="<html>recent</html>")
    cleanup_backups(backup_dir)
    assert not old_file.exists()
    assert recent_file.exists()


# ---------------------------------------------------------------------------
# cleanup_backups — non-matching filenames ignored
# ---------------------------------------------------------------------------


def test_cleanup_ignores_non_matching_filenames(backup_dir):
    # File that doesn't match the expected pattern
    odd_file = backup_dir / "some_other_file.html"
    odd_file.write_text("<html>other</html>", encoding="utf-8")
    cleanup_backups(backup_dir)
    assert odd_file.exists()


def test_cleanup_ignores_txt_files(backup_dir):
    txt_file = backup_dir / "notes.txt"
    txt_file.write_text("notes", encoding="utf-8")
    cleanup_backups(backup_dir)
    assert txt_file.exists()


def test_cleanup_ignores_partial_pattern(backup_dir):
    partial = backup_dir / "inventario_autostar_not_a_date.html"
    partial.write_text("<html></html>", encoding="utf-8")
    cleanup_backups(backup_dir)
    assert partial.exists()


# ---------------------------------------------------------------------------
# cleanup_backups — nonexistent directory
# ---------------------------------------------------------------------------


def test_cleanup_nonexistent_dir_no_error(tmp_path):
    nonexistent = tmp_path / "does_not_exist"
    # Should not raise
    cleanup_backups(nonexistent)


def test_cleanup_empty_dir_no_error(backup_dir):
    # Empty dir — nothing to do, should not raise
    cleanup_backups(backup_dir)
