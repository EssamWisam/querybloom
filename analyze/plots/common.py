"""Shared styling and helpers for paper-ready plots."""

import os
import matplotlib.pyplot as plt
import seaborn as sns

# Colour palette used across all figures
COLORS = ["#2E86C1", "#E67E22"]  # Steel Blue, Pumpkin Orange

# Apply once on import
plt.style.use("seaborn-v0_8-whitegrid")
sns.set_context("paper", font_scale=1.5)
plt.rcParams.update(
    {
        "figure.dpi": 150,
        "savefig.dpi": 600,
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "DejaVu Sans"],
    }
)

FIGURES_DIR = os.path.join(os.path.dirname(__file__), "..", "figures")


def save_fig(fig, name, extensions=("pdf",)):
    """Save *fig* to ``figures/<name>.<ext>`` for each extension."""
    os.makedirs(FIGURES_DIR, exist_ok=True)
    for ext in extensions:
        fig.savefig(
            os.path.join(FIGURES_DIR, f"{name}.{ext}"),
            dpi=600,
            bbox_inches="tight",
        )
