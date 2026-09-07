"""
Integration tests for the full update.py pipeline.

These tests execute `python3 update.py` as a subprocess inside a temporary
directory that mirrors the real project layout, using the `full_environment`
fixture from conftest.py.

Strategy: `update.py` resolves `script_dir` as `Path(__file__).resolve().parent`.
To point it at the test's config.json we copy update.py into tmp_path and run
it from there.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import SAMPLE_VEHICLES, write_csv, ALL_CSV_COLUMNS

# Absolute paths to real project files
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_UPDATE_PY = _PROJECT_ROOT / "update.py"
_REAL_TEMPLATE = _PROJECT_ROOT / "template.html"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_script(tmp_path: Path) -> Path:
    """Copy update.py into tmp_path so script_dir == tmp_path.
    Also replace the sample template with the real one so output passes 10 KB validation.
    """
    dest = tmp_path / "update.py"
    if not dest.exists():
        shutil.copy2(_UPDATE_PY, dest)

    # Replace the small sample template with the real project template
    real_template_dest = tmp_path / "template.html"
    if _REAL_TEMPLATE.exists():
        shutil.copy2(_REAL_TEMPLATE, real_template_dest)

    return dest


def _run(env: dict, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run a local copy of update.py from the tmp_path directory."""
    tmp_path: Path = env["tmp_path"]
    script = _setup_script(tmp_path)
    cmd = [sys.executable, str(script)]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _extract_json_data(html_content: str) -> list:
    """Extract the DATA array from the generated HTML.

    update.py serializes records as a JSON array and injects it into
    `const DATA = [/*%%DATA%%*/]`, producing `const DATA = [[{...},...]]`.
    We unwrap the outer array to return the actual records list.
    """
    marker = "const DATA = ["
    start = html_content.find(marker)
    if start == -1:
        return []
    # Find the matching closing bracket (accounting for nested brackets in JSON)
    bracket_start = start + len(marker) - 1  # points at '['
    depth = 0
    i = bracket_start
    bracket_end = -1
    while i < len(html_content):
        c = html_content[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                bracket_end = i
                break
        i += 1
    if bracket_end == -1:
        return []
    array_str = html_content[bracket_start:bracket_end + 1]  # includes [ and ]
    try:
        parsed = json.loads(array_str)
    except json.JSONDecodeError:
        return []
    # update.py injects json.dumps(records) into [/*%%DATA%%*/], producing [[...]].
    # Unwrap the outer array if needed.
    if len(parsed) == 1 and isinstance(parsed[0], list):
        return parsed[0]
    return parsed


def _make_extra_vehicles(n: int) -> list[dict]:
    """Generate n unique vehicle rows based on SAMPLE_VEHICLES[0]."""
    base = SAMPLE_VEHICLES[0]
    return [{**base, "vin": f"TEST{i:05d}", "inv": str(9000 + i)} for i in range(n)]


# ---------------------------------------------------------------------------
# Full end-to-end pipeline
# ---------------------------------------------------------------------------


def test_end_to_end_success(full_environment):
    """Given a valid CSV with 3 vehicles, the HTML must contain exactly 3 records."""
    result = _run(full_environment)
    assert result.returncode == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"

    html = full_environment["html_output_path"].read_text(encoding="utf-8")
    data = _extract_json_data(html)
    assert len(data) == len(SAMPLE_VEHICLES)


def test_end_to_end_vehicle_count_matches_csv(full_environment):
    """Write 10 vehicles to CSV; HTML must contain exactly 10."""
    vehicles = _make_extra_vehicles(10)
    write_csv(full_environment["csv_path"], vehicles, columns=ALL_CSV_COLUMNS)

    result = _run(full_environment)
    assert result.returncode == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"

    html = full_environment["html_output_path"].read_text(encoding="utf-8")
    data = _extract_json_data(html)
    assert len(data) == 10


def test_end_to_end_html_updated(full_environment):
    """After a successful run the HTML file must change."""
    # Write 5 fresh, unique vehicles (different from SAMPLE_VEHICLES)
    vehicles = _make_extra_vehicles(5)
    write_csv(full_environment["csv_path"], vehicles, columns=ALL_CSV_COLUMNS)

    html_before = full_environment["html_output_path"].read_text(encoding="utf-8")
    _run(full_environment)
    html_after = full_environment["html_output_path"].read_text(encoding="utf-8")
    assert html_before != html_after


def test_end_to_end_backup_created(full_environment):
    """A backup file must be created in backup_dir after a successful run."""
    backup_dir: Path = full_environment["backup_dir"]
    backups_before = list(backup_dir.glob("inventario_autostar_*.html"))

    _run(full_environment)

    backups_after = list(backup_dir.glob("inventario_autostar_*.html"))
    assert len(backups_after) > len(backups_before)


def test_end_to_end_log_written(full_environment):
    """Log file must exist and contain an [inicio] entry after a successful run."""
    _run(full_environment)
    log_path: Path = full_environment["log_path"]
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "[inicio]" in content


def test_end_to_end_log_contains_success(full_environment):
    """Log must contain an [output] line indicating how many vehicles were processed."""
    _run(full_environment)
    log_content = full_environment["log_path"].read_text(encoding="utf-8")
    assert "[output]" in log_content


# ---------------------------------------------------------------------------
# --dry-run: HTML not modified
# ---------------------------------------------------------------------------


def test_dry_run_html_not_modified(full_environment):
    """With --dry-run the App_HTML must not be changed."""
    html_before = full_environment["html_output_path"].read_text(encoding="utf-8")
    result = _run(full_environment, extra_args=["--dry-run"])
    assert result.returncode == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    html_after = full_environment["html_output_path"].read_text(encoding="utf-8")
    assert html_before == html_after


def test_dry_run_no_backup_created(full_environment):
    """With --dry-run no backup should be created."""
    backup_dir: Path = full_environment["backup_dir"]
    backups_before = list(backup_dir.glob("inventario_autostar_*.html"))
    _run(full_environment, extra_args=["--dry-run"])
    backups_after = list(backup_dir.glob("inventario_autostar_*.html"))
    assert len(backups_after) == len(backups_before)


def test_dry_run_stdout_reports_vehicle_count(full_environment):
    """--dry-run must print the number of vehicles that would be processed."""
    result = _run(full_environment, extra_args=["--dry-run"])
    combined = result.stdout + result.stderr
    assert str(len(SAMPLE_VEHICLES)) in combined


# ---------------------------------------------------------------------------
# Missing CSV → exit 1, HTML unchanged
# ---------------------------------------------------------------------------


def test_missing_csv_exits_with_code_1(full_environment):
    """If the CSV is deleted, the script must exit with code 1."""
    full_environment["csv_path"].unlink()
    result = _run(full_environment)
    assert result.returncode == 1, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"


def test_missing_csv_html_unchanged(full_environment):
    """If the CSV is missing, the App_HTML must not be modified."""
    html_before = full_environment["html_output_path"].read_text(encoding="utf-8")
    full_environment["csv_path"].unlink()
    _run(full_environment)
    html_after = full_environment["html_output_path"].read_text(encoding="utf-8")
    assert html_before == html_after


def test_missing_csv_log_contains_error(full_environment):
    """The log must contain an error message when the CSV is missing."""
    full_environment["csv_path"].unlink()
    _run(full_environment)
    log_path: Path = full_environment["log_path"]
    assert log_path.exists(), "Log file should be created even on error"
    log_content = log_path.read_text(encoding="utf-8")
    assert "ERROR" in log_content or "error" in log_content.lower()


# ---------------------------------------------------------------------------
# Lock file present → exit 0, no processing
# ---------------------------------------------------------------------------


def test_lock_present_exits_with_code_0(full_environment):
    """If the lock file already exists the script must exit with code 0."""
    tmp_path: Path = full_environment["tmp_path"]
    _setup_script(tmp_path)  # ensure update.py copy exists
    lock_path = tmp_path / "actualizacion.lock"
    lock_path.touch()
    try:
        result = _run(full_environment)
        assert result.returncode == 0, f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    finally:
        if lock_path.exists():
            lock_path.unlink()


def test_lock_present_html_not_modified(full_environment):
    """With a pre-existing lock, the App_HTML must remain unchanged."""
    tmp_path: Path = full_environment["tmp_path"]
    _setup_script(tmp_path)
    html_before = full_environment["html_output_path"].read_text(encoding="utf-8")

    lock_path = tmp_path / "actualizacion.lock"
    lock_path.touch()
    try:
        _run(full_environment)
    finally:
        if lock_path.exists():
            lock_path.unlink()

    html_after = full_environment["html_output_path"].read_text(encoding="utf-8")
    assert html_before == html_after


def test_lock_cleaned_up_after_successful_run(full_environment):
    """After a successful run the lock file must not remain."""
    tmp_path: Path = full_environment["tmp_path"]
    _setup_script(tmp_path)
    lock_path = tmp_path / "actualizacion.lock"

    _run(full_environment)

    assert not lock_path.exists()
