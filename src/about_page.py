"""About Uptrend Ratio page: what the ratio counts, in plain words and pictures.

The page is one HTML block rendered with st.html. st.html sanitizes its input and
drops inline <svg>, so each picture is a standalone SVG embedded as a data: URI
<img>. Each picture has its own white background and light-theme colors, so
it stays legible whichever Streamlit theme the viewer picks.
Nothing depends on JavaScript. The example numbers come from the latest
whole-market row, so the page never shows a stale "today".
Line colors follow the real charts (chart_builder COLOR_TREND_UP/DOWN, COLOR_MA,
COLOR_UPPER/LOWER). Text and background inherit the Streamlit theme; the page CSS
is scoped to .about-ur so it cannot leak into other elements.
"""

import base64
import html
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src.chart_builder import (
    COLOR_LOWER,
    COLOR_MA,
    COLOR_OVERSOLD_BAND,
    COLOR_TREND_DOWN,
    COLOR_TREND_UP,
    COLOR_UPPER,
)
from src.constants import LOWER_THRESHOLD, UPPER_THRESHOLD
from src.kpi_cards import uptrend_screener_url
from src.page_footer import UPTREND_ANALYZER_SKILL_URL


@dataclass(frozen=True)
class RatioExample:
    """One day of the whole-market count, used as the page's worked example."""

    date: pd.Timestamp
    count: int
    total: int

    @property
    def ratio(self) -> float:
        return self.count / self.total


def latest_example(df: Optional[pd.DataFrame]) -> Optional[RatioExample]:
    """The last row with a usable count/total, or None (the page then skips the numbers)."""
    if df is None or df.empty or not {"date", "count", "total"} <= set(df.columns):
        return None
    usable = df.dropna(subset=["date", "count", "total"]).sort_values("date")
    usable = usable[usable["total"] > 0]
    if usable.empty:
        return None
    row = usable.iloc[-1]
    return RatioExample(pd.Timestamp(row["date"]), int(row["count"]), int(row["total"]))


def _fmt_date(d: pd.Timestamp) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _pct(x: float) -> str:
    """0.37 -> "37%", 0.097 -> "9.7%" (as the chart labels them)."""
    return f"{x * 100:g}%"


# Colors used inside the pictures (the app theme is light).
_SVG_STYLE = (
    "<style>"
    ".big{fill:#1f2430;font:700 34px sans-serif}.lbl{fill:#5f6675;font:14px sans-serif}"
    ".dot{fill:#c8ced8}.up{fill:#087a4d}.price{stroke:#087a4d}.axis{stroke:#d9dee6}"
    ".pink{fill:rgba(233,30,99,.10)}.deep{fill:rgba(233,30,99,.28)}"
    "</style>"
)


def svg_document(body: str, height: int, label: str) -> str:
    """A standalone 360-wide SVG (the width keeps 14px labels readable on phones)."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 {height}" role="img">'
        f"<title>{html.escape(label)}</title>{_SVG_STYLE}"
        f'<rect width="360" height="{height}" rx="8" fill="#ffffff"/>{body}</svg>'
    )


def _img(svg: str, label: str) -> str:
    data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img class="pic" alt="{html.escape(label)}" src="data:image/svg+xml;base64,{data}">'


def _picture(body: str, height: int, label: str) -> str:
    return _img(svg_document(body, height, label), label)


STYLE = """
<style>
.about-ur{--good:#087a4d;--accent:#1f77b4;--card:rgba(128,128,128,.10);
  --pink:rgba(233,30,99,.10);max-width:760px;line-height:1.55}
.about-ur h1{font-size:1.9rem;margin:.2em 0 .3em;padding:0}
.about-ur .lead{font-size:1.25rem;font-weight:600;margin:0 0 20px}
.about-ur .lead b{color:var(--good)}
.about-ur h2{font-size:1.2rem;margin:32px 0 10px;padding:0}
.about-ur .card{background:var(--card);border-radius:12px;padding:16px 18px;margin:12px 0}
.about-ur img.pic{width:100%;height:auto;display:block;max-width:560px;margin:0 auto}
.about-ur ul.checks{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.about-ur ul.checks li{background:var(--card);border-radius:10px;padding:10px 12px;border-left:4px solid var(--good);margin:0}
.about-ur ul.checks li span{display:block;opacity:.75;font-size:.85rem}
.about-ur ul.base li{border-left-color:var(--accent)}
.about-ur .formula{font-size:1.2rem;text-align:center}
.about-ur .n{color:var(--good);font-weight:700}
.about-ur .d{color:var(--accent);font-weight:700}
.about-ur .legend{display:grid;grid-template-columns:38px 1fr;gap:10px 12px;align-items:center;margin-top:14px}
.about-ur .sw{width:34px;height:0;border-top:4px solid}
.about-ur .sw.dotted{border-top-style:dotted;border-top-width:3px}
.about-ur .sw.box{height:14px;border:0;border-radius:3px;background:var(--pink)}
.about-ur .btn{display:inline-block;background:#1f77b4;color:#fff;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:600;margin:6px 8px 6px 0}
.about-ur .btn.alt{background:transparent;color:var(--accent);border:1.5px solid var(--accent)}
.about-ur .note{opacity:.75;font-size:.9rem;margin:10px 0 0}
.about-ur .sowhat{margin-top:32px;font-size:1.1rem;font-weight:600;border-top:1px solid var(--card);padding-top:16px}
.about-ur .disclaimer{opacity:.7;font-size:.85rem}
</style>
"""


def green_dot_count(ex: RatioExample) -> int:
    # count/total x 100 rounded half up, in integers (0.145 * 100 is 14.4999... in floats)
    return max(0, min(100, (200 * ex.count + ex.total) // (2 * ex.total)))


def _dots_label(ex: RatioExample) -> str:
    return (f"100 dots, {green_dot_count(ex)} of them green: {ex.ratio:.1%} of stocks were in an uptrend "
            f"on {_fmt_date(ex.date)}")


def dots_svg(ex: RatioExample) -> str:
    """100 dots, one per percent; the green ones are the uptrend share."""
    green = green_dot_count(ex)
    dots = "".join(
        f'<circle class="dot{" up" if i < green else ""}" cx="{14 + i % 10 * 16}" cy="{14 + i // 10 * 16}" r="6"/>'
        for i in range(100)
    )
    when = _fmt_date(ex.date)
    body = (
        f'{dots}<text x="196" y="70" class="big">{ex.ratio:.1%}</text>'
        '<text x="200" y="96" class="lbl">in an uptrend</text>'
        f'<text x="200" y="116" class="lbl">on {when}</text>'
    )
    return svg_document(body, 170, _dots_label(ex))


def _dots_section(ex: RatioExample) -> str:
    label = _dots_label(ex)
    return f"""
<h2>1. Shrink the market to 100 stocks</h2>
<div class="card">
{_img(dots_svg(ex), label)}
<p class="note">About {green_dot_count(ex)} of the 100 dots are green: they pass every uptrend check below. Each dot stands for about {round(ex.total / 100):,} real stocks.
These are the latest numbers on the dashboard.</p>
</div>"""


_AVERAGES_SVG = (
    '<line class="axis" x1="10" y1="190" x2="350" y2="190"/>'
    '<path d="M10 175 C110 172 220 160 350 140" fill="none" stroke="#9aa3b2" stroke-width="3"/>'
    '<path d="M10 160 C110 145 220 115 350 90" fill="none" stroke="#ff7f0e" stroke-width="3"/>'
    '<path d="M10 150 C110 128 220 92 350 62" fill="none" stroke="#1f77b4" stroke-width="2.5" stroke-dasharray="6 4"/>'
    '<path class="price" d="M10 130 L40 112 L65 120 L95 96 L120 104 L150 80 L175 88 L205 62 L230 70 L260 46 '
    'L290 52 L320 30 L350 22" fill="none" stroke-width="3.5"/>'
)


def _chart_svg(upper: str, lower: str) -> str:
    return (
        '<rect class="pink" x="150" y="10" width="112" height="180"/>'
        '<rect class="deep" x="250" y="10" width="30" height="180"/>'
        f'<line x1="10" y1="40" x2="350" y2="40" stroke="{COLOR_UPPER}" stroke-width="2" stroke-dasharray="3 4"/>'
        f'<text x="14" y="32" class="lbl">{upper}</text>'
        f'<line x1="10" y1="165" x2="350" y2="165" stroke="{COLOR_LOWER}" stroke-width="2" stroke-dasharray="3 4"/>'
        f'<text x="14" y="185" class="lbl">{lower}</text>'
        '<path d="M10 140 C60 118 110 72 150 64 C190 72 230 128 260 140 C290 134 320 112 350 100" fill="none" '
        f'stroke="{COLOR_MA}" stroke-width="2"/>'
        '<path d="M10 150 L30 128 L50 135 L70 105 L90 112 L110 80 L130 72 L150 52" fill="none" '
        f'stroke="{COLOR_TREND_UP}" stroke-width="3"/>'
        '<path d="M150 52 L170 78 L190 70 L210 110 L230 118 L245 158 L255 174 L262 178" fill="none" '
        f'stroke="{COLOR_TREND_DOWN}" stroke-width="3"/>'
        f'<path d="M262 178 L280 150 L290 128 L300 136 L320 108 L350 92" fill="none" stroke="{COLOR_TREND_UP}" stroke-width="3"/>'
    )


def _formula(ex: Optional[RatioExample], number: int) -> str:
    numbers = ""
    if ex is not None:
        numbers = (
            f'<br><span class="n">{ex.count:,}</span> ÷ <span class="d">{ex.total:,}</span> = <b>{ex.ratio:.1%}</b>'
            f'<p class="note">Whole market on {_fmt_date(ex.date)}.</p>'
        )
    return f"""
<h2>{number}. The ratio</h2>
<div class="card formula">
<span class="n">Stocks in an uptrend</span> ÷ <span class="d">Stocks counted</span>{numbers}
<p class="note">Counted every trading day for the whole market, 11 sectors and 149 industries.</p>
</div>"""


def about_page_html(example: Optional[RatioExample]) -> str:
    """The whole page as one HTML string. `example=None` leaves out the live numbers."""
    n = 1 if example is not None else 0  # section numbers shift when the dots are left out
    screen = html.escape(uptrend_screener_url() or "https://finviz.com/screener/stocks")
    upper, lower = _pct(UPPER_THRESHOLD), _pct(LOWER_THRESHOLD)
    averages = _picture(
        _AVERAGES_SVG, 200,
        "The price line is above its 20-day and 200-day averages, "
        "and the 50-day average is above the 200-day average",
    )
    chart = _picture(
        _chart_svg(upper, lower), 200,
        f"Example chart: the ratio line is green while its purple 10-day average rises and red, "
        f"with pink shading, while it falls; deeper pink where it drops below {lower}; "
        f"dotted lines mark {upper} and {lower}",
    )
    return STYLE + f"""
<div class="about-ur">
<h1>What is the Uptrend Ratio?</h1>
<p class="lead">The share of US-listed stocks that are in an uptrend. <b>Higher = more stocks rising together.</b></p>
{_dots_section(example) if example is not None else ""}

<h2>{1 + n}. Who is counted? (the denominator)</h2>
<ul class="checks base">
<li>Market cap over $50M<span>Not tiny companies</span></li>
<li>Average volume over 100K shares<span>Actually traded</span></li>
<li>Price over $10<span>Not low-priced stocks</span></li>
</ul>
<p class="note">ETFs that pass these checks are counted too.</p>

<h2>{2 + n}. Who is in an uptrend? (the numerator)</h2>
<p>A stock that passes the 3 checks above, plus all 5 of these:</p>
<div class="card">
{averages}
<div class="legend">
<div class="sw" style="border-color:var(--good)"></div><div>Price: above the 20-day and the 200-day average</div>
<div class="sw" style="border-color:#1f77b4;border-top-style:dashed"></div><div>20-day average</div>
<div class="sw" style="border-color:#ff7f0e"></div><div>50-day average: must be above the 200-day</div>
<div class="sw" style="border-color:#9aa3b2"></div><div>200-day average</div>
</div>
</div>
<ul class="checks">
<li>Price above its 20-day average<span>Rising in the short term</span></li>
<li>Price above its 200-day average<span>Rising in the long term</span></li>
<li>50-day average above the 200-day average<span>The trend itself points up</span></li>
<li>30% or more above its 52-week low<span>Well off the bottom</span></li>
<li>Up over the past month<span>Still moving now</span></li>
</ul>
{_formula(example, 3 + n)}

<h2>{4 + n}. How to read the chart</h2>
<div class="card">
{chart}
<div class="legend">
<div class="sw" style="border-color:{COLOR_MA};border-top-width:2px"></div><div>Purple line: the 10-day average of the ratio</div>
<div class="sw" style="border-color:{COLOR_TREND_UP}"></div><div>Green: the 10-day average is rising</div>
<div class="sw" style="border-color:{COLOR_TREND_DOWN}"></div><div>Red: the 10-day average is falling or flat</div>
<div class="sw box"></div><div>Pink shading: the red stretches (Uptrend Ratio page, both panels)</div>
<div class="sw box" style="background:{COLOR_OVERSOLD_BAND}"></div><div>Deeper pink: the ratio is below {lower} (Oversold)</div>
<div class="sw dotted" style="border-color:{COLOR_UPPER}"></div><div>Dotted {upper} line: many stocks are already stretched. In the past, rallies have often paused around here.</div>
<div class="sw dotted" style="border-color:{COLOR_LOWER}"></div><div>Dotted {lower} line: very few stocks are rising. In the past, selloffs have often ended around here.</div>
</div>
<p class="note">Solid lines are the ratio; dotted lines are fixed levels. On the Uptrend Ratio page, the S&amp;P 500 sits above the ratio for comparison. The levels are context, not buy or sell signals.</p>
</div>

<h2>{5 + n}. See the stocks yourself</h2>
<a class="btn" href="{screen}" target="_blank" rel="noopener noreferrer">Open the uptrend screen on Finviz →</a>
<a class="btn alt" href="{UPTREND_ANALYZER_SKILL_URL}" target="_blank" rel="noopener noreferrer">Analyze it with AI: Uptrend Analyzer skill →</a>
<p class="note">The Finviz screen uses the same 8 checks and shows today's list. It lists stocks only, so its count can be a few lower than the dashboard's, which also includes ETFs.</p>

<p class="sowhat">So what: a high, rising ratio means the rally is broad. A low ratio means only a few stocks are carrying the market.</p>
<p class="disclaimer">For information only. Not investment advice.</p>
</div>
"""
