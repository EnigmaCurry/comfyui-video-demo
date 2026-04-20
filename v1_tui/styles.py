"""Load prompt styles from the styles/ directory."""

import json
import os
import sys

STYLES_DIR = os.path.join(os.path.dirname(__file__), "styles")
DEFAULT_STYLE = "absurd-realism"


def list_styles():
    """Return sorted list of available style names."""
    styles = []
    for f in os.listdir(STYLES_DIR):
        if f.endswith(".json"):
            styles.append(f[:-5])
    return sorted(styles)


def load_style(name):
    """Load a style by name. Returns dict with keys:
    visual_system_prompt, base_prompt, voiceover_system_prompt (may be None).
    """
    path = os.path.join(STYLES_DIR, f"{name}.json")
    if not os.path.exists(path):
        available = ", ".join(list_styles()) or "(none)"
        print(f"Error: unknown style '{name}'. Available: {available}",
              file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)
