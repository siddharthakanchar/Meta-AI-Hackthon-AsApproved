"""AsApproved — Streamlit entry point.

Phase 0 ships the shell: navigation, theme and an honest "not built yet" state on
every screen, so the app is launchable from the first commit. Phase 5 builds the
hero screen (§11 screen 2).
"""

from __future__ import annotations

import streamlit as st

from asapproved import RULEBOOK_VERSION, __version__
from asapproved.config import settings

st.set_page_config(
    page_title="AsApproved",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

ACCENT_FAIL = "#e5484d"  # one accent colour, reserved for failures (§11)

st.markdown(
    f"""
    <style>
      .block-container {{ padding-top: 2.2rem; }}
      .aa-metric {{ font-size: 2.4rem; font-weight: 650; line-height: 1.1; }}
      .aa-fail {{ color: {ACCENT_FAIL}; }}
      .aa-muted {{ opacity: .65; font-size: .85rem; }}
      .aa-sim {{
        display:inline-block; padding:.1rem .45rem; border-radius:.25rem;
        border:1px solid currentColor; font-size:.7rem; letter-spacing:.06em;
        text-transform:uppercase; opacity:.8;
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

SCREENS = {
    "Overview": "Phase 5",
    "Variant review": "Phase 5",
    "Blast radius": "Phase 6",
    "Evidence": "Phase 5",
    "Benchmark": "Phase 6",
    "Ask the reviewer": "Phase 6",
}

with st.sidebar:
    st.markdown("### AsApproved")
    st.caption("Turn on Advantage+ without betting your licence.")
    screen = st.radio("Screen", list(SCREENS), label_visibility="collapsed")
    st.divider()
    st.caption(f"v{__version__} · rulebook `{RULEBOOK_VERSION}`")
    st.caption(f"mode `{settings.mode}`" + (" · cache only" if settings.offline else " · live"))

st.title(screen)
st.info(
    f"Not built yet — this screen lands in {SCREENS[screen]}. "
    "The app is kept launchable from Phase 0 onward so every phase ends demo-able."
)

st.markdown(
    '<span class="aa-sim">simulated</span> '
    '<span class="aa-muted">Every variant not fetched from Meta is labelled like this, '
    "here, in the dataset and in the README.</span>",
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="aa-muted">Findings flag items for compliance review against paraphrased '
    "regulation. Not legal advice.</p>",
    unsafe_allow_html=True,
)
