"""Coverage captions on the real pages (PR #45 review: M2, H1)."""

from tests.test_detail_navigation import detail_app, loaded_data, select_label  # noqa: F401

MANIFEST = {
    "session_date": "2026-11-20", "scope": "all", "aborted": None,
    "coverage": {"expected": 3, "fetched": 2, "persisted": 2, "empty": 0, "failed": 1,
                 "missing": 0, "stored": 2},
    "worksheets": {
        "ind_semiconductors": {"outcome": "persisted", "stored": True},
        "ind_biotechnology": {"outcome": "persisted", "stored": True},
        "ind_gold": {"outcome": "failed", "stored": False},
    },
}


def _captions(app):
    return [c.value for c in app.caption if c.value.startswith("Collection ")]


def test_sector_caption_counts_only_that_sectors_industries(loaded_data, mocker):
    mocker.patch("src.data_loader.cached_load_manifest", return_value=MANIFEST)
    app = detail_app("1_Sector_Detail.py").run()
    app = select_label(app, "Select Sector", "Technology")
    assert _captions(app) == ["Collection 2026-11-20 (Technology industries): 1 of 1 stored"]


def test_heatmap_caption_says_unpublished_run_failed(loaded_data, mocker):
    mocker.patch("src.data_loader.cached_load_manifest",
                 return_value={**MANIFEST, "data_published": False})
    mocker.patch("src.data_loader.cached_load_all_constituents", return_value=None)
    app = detail_app("5_Industry_Heatmap.py").run()
    captions = _captions(app)
    assert captions == ["Collection 2026-11-20: run failed, data not published · 1 failed"]
