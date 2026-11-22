"""Page footer: link to the Uptrend Analyzer skill (Claude Trading Skills).

Same wording and look as the AI note on the Market Breadth Analysis page
(https://tradermonty.github.io/market-breadth-analysis/).
"""

UPTREND_ANALYZER_SKILL_URL = (
    "https://tradermonty.github.io/claude-trading-skills/en/skills/uptrend-analyzer/"
)


def ai_skill_note_html() -> str:
    return (
        '<p style="text-align:center;color:#777;font-size:0.85em;margin:18px 0 4px;line-height:1.5;">'
        "Want to analyze this uptrend data with AI? "
        f'<a href="{UPTREND_ANALYZER_SKILL_URL}" target="_blank" rel="noopener" '
        'style="color:#0366d6;text-decoration:none;">'
        "Try the Uptrend Analyzer skill for Claude &rarr;</a></p>"
    )


def render_ai_skill_note() -> None:
    import streamlit as st

    st.markdown(ai_skill_note_html(), unsafe_allow_html=True)


# Daily one-minute explainer pages written by Claude and published to GitHub Pages
# (see run_explainer.py). English is the primary language; Japanese is offered alongside.
EXPLAINER_URL = "https://tradermonty.github.io/uptrend-dashboard/"


def explainer_link_html() -> str:
    link = 'target="_blank" rel="noopener" style="color:#0366d6;text-decoration:none;"'
    return (
        '<p style="font-size:0.9em;margin:2px 0 10px;">'
        "New to market breadth? "
        f'<a href="{EXPLAINER_URL}latest/en.html" {link}>'
        "Read today's one-minute explainer &rarr;</a>"
        ' <span style="color:#777;">·</span> '
        f'<a href="{EXPLAINER_URL}latest/ja.html" lang="ja" {link}>日本語で読む</a></p>'
    )


def render_explainer_link() -> None:
    import streamlit as st

    st.markdown(explainer_link_html(), unsafe_allow_html=True)
