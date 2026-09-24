"""Filtration pipeline for the AI Steward Dashboard.

Six cheap gates in front of one expensive call:

    probe -> validate -> normalise + hash -> diff -> cosmetic gate
          -> fingerprint -> LLM

Each stage lives in its own module and is importable on its own, so the gates
can be tested without a network, a browser or an API key.
"""

# Bumped whenever a change to extraction or normalisation makes stored
# snapshots incomparable with freshly captured ones. main.py re-baselines
# instead of reporting a change that did not happen.
#
# 3: bodies served without a declared charset are decoded as UTF-8 rather
#    than requests' ISO-8859-1 default, which had Google's AI Principles page
#    alternating between an em dash and a stray 'â' from run to run.
PIPELINE_VERSION = 3

__all__ = ["PIPELINE_VERSION"]
