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
