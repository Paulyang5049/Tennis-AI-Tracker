"""Render README figures from the checked-in local validation snapshot."""

import json
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "docs/data/validation-2026-09-10.json").read_text())
OUT = ROOT / "docs/images"
GREEN, INK, CREAM, LIME, MUTED = "#173F35", "#183C33", "#F6F5ED", "#D5E84C", "#64766F"
plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.labelcolor": INK})


def base(title, subtitle, height):
    fig = plt.figure(figsize=(14, height), facecolor=CREAM)
    fig.text(0.055, 0.92, title, fontsize=26, weight="bold")
    fig.text(0.055, 0.85, subtitle, fontsize=12, color=MUTED)
    return fig


def save(fig, name):
    fig.savefig(OUT / name, dpi=160, facecolor=CREAM)
    plt.close(fig)


fig = base(
    "Local validation, at a glance",
    f"Measured {date.fromisoformat(DATA['date']).strftime('%d %b %Y')}  /  development build",
    5.6,
)
video, native = DATA["full_video"], DATA["native_excerpt"]
cards = [
    (
        f"{DATA['python_tests']['passed']} / {DATA['python_tests']['total']}",
        "Python tests",
        "Automated suite",
    ),
    (
        f"{DATA['swift_tests']['passed']} / {DATA['swift_tests']['total']}",
        "Swift tests",
        "Core contract + storage",
    ),
    (
        f"{video['frames']:,}",
        "Full-video frames",
        f"Expected {video['expected_frames']:,} / "
        + ("all retained" if video["frames"] == video["expected_frames"] else "count mismatch"),
    ),
    (
        f"{native['frames']} / {native['ffmpeg_frames']}",
        "Native excerpt frames",
        "Matches FFmpeg decoding",
    ),
]
for i, (value, label, detail) in enumerate(cards):
    ax = fig.add_axes((0.055 + i * 0.23, 0.38, 0.21, 0.36), facecolor=GREEN)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.text(0.08, 0.65, value, color=LIME, size=27, weight="bold", transform=ax.transAxes)
    ax.text(0.08, 0.37, label, color="white", size=13, transform=ax.transAxes)
    ax.text(0.08, 0.17, detail, color="#D7E2DB", size=9, transform=ax.transAxes)
fig.text(
    0.055,
    0.24,
    "Also passed: lint + types  |  iOS simulator / unsigned device builds  |  audio clip export",
    size=12,
)
fig.text(
    0.055,
    0.13,
    "Scope: software checks. Phone performance and detection accuracy remain unverified.",
    size=12,
    color=MUTED,
)
save(fig, "validation-checks.png")

fig = base(
    "One complete broadcast clip",
    f"{round(video['duration_seconds']) // 60} min {round(video['duration_seconds']) % 60} sec  /  {video['width']:,} × {video['height']:,}  /  {video['frames']:,} frames  /  audio retained",
    7.2,
)
ax = fig.add_axes((0.18, 0.49, 0.76, 0.25), facecolor=CREAM)
observed = video["ball_observed"] * 100
interpolated = video["ball_interpolated"] * 100
court = video["court_calibrated"] * 100
for y, widths, colors in [
    (1, [observed, interpolated, 100 - observed - interpolated], [GREEN, LIME, "#DEE3DC"]),
    (0, [court, 100 - court], [GREEN, "#DEE3DC"]),
]:
    left = 0
    for width, color in zip(widths, colors):
        ax.barh(y, width, left=left, height=0.45, color=color)
        ax.text(
            left + width / 2,
            y,
            f"{width:.1f}%",
            va="center",
            ha="center",
            color="white" if color == GREEN else INK,
            size=11,
        )
        left += width
ax.set_yticks([1, 0], ["Ball availability", "Court calibrated"])
ax.set_xlim(0, 100)
ax.set_xticks([])
ax.tick_params(axis="y", length=0, labelsize=12)
for spine in ax.spines.values():
    spine.set_visible(False)
fig.text(
    0.18,
    0.44,
    "Ball: observed (green) / interpolated (yellow) / missing (grey)",
    size=11,
    color=MUTED,
)
fig.text(
    0.055,
    0.33,
    f"{sum(video['candidates'].values())} unreviewed event candidates",
    fontsize=18,
    weight="bold",
)
for i, (kind, count) in enumerate(video["candidates"].items()):
    fig.text(0.055 + i * 0.28, 0.24, f"{count}  {kind.lower()}", size=22, weight="bold")
fig.text(
    0.055,
    0.15,
    f"{video['reviewed_events']} confirmed events. Candidate counts are not match statistics.",
    size=12,
)
fig.text(
    0.055,
    0.065,
    "Coverage is not accuracy. Scoreboard false positives and unstable player IDs were observed.",
    size=12,
    color=MUTED,
)
save(fig, "validation-broadcast.png")
