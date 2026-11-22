"""Tests for sidebar navigation definitions."""

from pathlib import Path

from src.navigation import PAGE_SPECS

ROOT = Path(__file__).resolve().parent.parent


def test_first_page_is_named_uptrend_ratio_not_app():
    assert PAGE_SPECS[0].title == "Uptrend Ratio"
    assert PAGE_SPECS[0].default is True


def test_only_one_default_page():
    assert sum(spec.default for spec in PAGE_SPECS) == 1


def test_every_page_file_exists():
    for spec in PAGE_SPECS:
        assert (ROOT / spec.path).is_file(), spec.path


def test_every_file_in_pages_dir_is_registered():
    registered = {spec.path for spec in PAGE_SPECS}
    on_disk = {f"pages/{p.name}" for p in (ROOT / "pages").glob("*.py")}
    assert on_disk == registered


def test_switch_page_targets_are_registered():
    registered = {spec.path for spec in PAGE_SPECS}
    for target in ("pages/1_Sector_Detail.py", "pages/3_Industry_Detail.py", "pages/6_Dispersion_Monitor.py"):
        assert target in registered
