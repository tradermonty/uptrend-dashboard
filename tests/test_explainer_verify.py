"""Facts extraction and the HTML gate that blocks wrong numbers from being published."""

import json

import pytest

from explainer.facts import Facts, build_facts
from explainer.verify import verify_html

FACTS = Facts(date="2026-11-20", ratio_pct=6.9, count=183, total=2661,
              score=22.4, zone="Cautious", exposure="Defensive (30-60%)")


def _page(lang="ja", facts=None, body="", extra_head=""):
    data = facts if facts is not None else {
        "date": "2026-11-20", "ratio_pct": 6.9, "count": 183, "total": 2661, "score": 22.4,
    }
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        f"<title>Uptrend</title>{extra_head}"
        f'<script type="application/json" id="uptrend-facts">{json.dumps(data)}</script>'
        f"</head><body>{body}</body></html>"
    )


GOOD_BODY = ('<h1>100社のうち7社</h1><p>2,661社のうち<span data-fact="count">183社</span>'
             '（<span data-fact="ratio_pct">6.9%</span>）</p>'
             '<p>スコア <span data-fact="score">22</span> / 100</p>')


class TestBuildFacts:

    def test_from_timeseries_and_report(self, tmp_path):
        ts = tmp_path / "ts.csv"
        ts.write_text(
            "worksheet,date,count,total,ratio,ma_10,slope,trend\n"
            "all,2026-11-19,264,2687,0.0982,0.19,-0.01,down\n"
            "all,2026-11-20,183,2661,0.06877113866967305,0.18,-0.01,down\n"
            "sec_energy,2026-11-20,0,151,0.0,0.02,-0.001,down\n"
        )
        report = {"composite": {"composite_score": 22.4, "zone": "Cautious",
                                "exposure_guidance": "Defensive (30-60%)"}}
        assert build_facts(ts, report) == FACTS

    def test_to_dict_round_trip(self):
        assert Facts(**FACTS.to_dict()) == FACTS


class TestVerifyHtml:

    def test_good_page_passes(self):
        assert verify_html(_page(body=GOOD_BODY), FACTS, "ja") == []

    def test_english_page_passes(self):
        body = ('<p>Of 2,661 stocks, <b data-fact="count">183</b> (<b data-fact="ratio_pct">6.9 %</b>)'
                ' are rising. Score <b data-fact="score">22.4</b> / 100.</p>')
        assert verify_html(_page("en", body=body), FACTS, "en") == []

    def test_wrong_lang_attribute(self):
        assert any("lang" in p for p in verify_html(_page("en", body=GOOD_BODY), FACTS, "ja"))

    def test_missing_facts_block(self):
        html = _page(body=GOOD_BODY).replace('id="uptrend-facts"', 'id="other"')
        assert any("uptrend-facts" in p for p in verify_html(html, FACTS, "ja"))

    @pytest.mark.parametrize("key,value", [
        ("date", "2026-11-19"), ("ratio_pct", 7.0), ("count", 184), ("total", 2600), ("score", 30.0),
    ])
    def test_facts_block_mismatch(self, key, value):
        data = {"date": "2026-11-20", "ratio_pct": 6.9, "count": 183, "total": 2661, "score": 22.4}
        data[key] = value
        problems = verify_html(_page(facts=data, body=GOOD_BODY), FACTS, "ja")
        assert any(key in p for p in problems)

    @pytest.mark.parametrize("missing", ["6.9%", "183", "22"])
    def test_visible_number_missing(self, missing):
        body = GOOD_BODY.replace(missing, "?")
        assert any(missing in p for p in verify_html(_page(body=body), FACTS, "ja"))

    def test_number_outside_labelled_element_does_not_count(self):
        body = "<p>183 stocks, 6.9%, score 22</p>"
        problems = verify_html(_page(body=body), FACTS, "ja")
        assert any("data-fact" in p for p in problems)

    def test_wrong_number_in_labelled_element(self):
        body = GOOD_BODY.replace('data-fact="score">22<', 'data-fact="score">7<')
        assert any("score" in p for p in verify_html(_page(body=body), FACTS, "ja"))

    def test_region_lang_and_fullwidth_percent_pass(self):
        body = GOOD_BODY.replace("6.9%", "6.9％")
        assert verify_html(_page("ja-JP", body=body), FACTS, "ja") == []

    def test_non_object_facts_block_is_a_problem(self):
        html = _page(facts=[1, 2], body=GOOD_BODY)
        assert any("uptrend-facts" in p for p in verify_html(html, FACTS, "ja"))

    def test_missing_body_tag(self):
        html = _page(body=GOOD_BODY).replace("<body>", "").replace("</body>", "")
        assert any("body" in p for p in verify_html(html, FACTS, "ja"))

    def test_numbers_only_inside_script_do_not_count(self):
        body = "<p>no numbers here</p>"
        assert verify_html(_page(body=body), FACTS, "ja") != []

    @pytest.mark.parametrize("head", [
        '<script src="https://cdn.example.com/x.js"></script>',
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=X">',
        '<style>body{background:url(https://example.com/a.png)}</style>',
        '<script src="//cdn.example.com/x.js"></script>',
        '<img src="//example.com/a.png">',
    ])
    def test_external_resources_rejected(self, head):
        problems = verify_html(_page(body=GOOD_BODY, extra_head=head), FACTS, "ja")
        assert any("external" in p for p in problems)

    def test_missing_title(self):
        html = _page(body=GOOD_BODY).replace("<title>Uptrend</title>", "")
        assert any("title" in p for p in verify_html(html, FACTS, "ja"))
