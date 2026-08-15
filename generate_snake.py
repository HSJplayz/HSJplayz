
#!/usr/bin/env python3
"""
Generates an animated SVG of a snake that walks ONLY through days with
0 contributions, treating days that have contributions as walls it
must avoid (rather than eating them).

Usage:
    GITHUB_TOKEN=xxx GITHUB_USER=xxx python generate_snake.py output.svg [--dark] [--pixel]
"""

import os
import sys
import json
import argparse
import requests

CELL = 12          # px size of one day cell
GAP = 3            # px gap between cells
RADIUS = 2          # corner radius of a cell
SNAKE_LEN = 5        # number of body segments
STEP_DURATION = 0.20  # seconds the snake takes to move one cell

THEMES = {
    "light": {
        "bg": "transparent",
        "empty": "#ebedf0",
        "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "snake_head": "#0969da",
        "snake_body": "#54aeff",
    },
    "dark": {
        "bg": "transparent",
        "empty": "#161b22",
        "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"],
        "snake_head": "#58a6ff",
        "snake_body": "#1f6feb",
    },
}


def fetch_contributions(user, token):
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            weeks {
              contributionDays {
                date
                weekday
                contributionCount
              }
            }
          }
        }
      }
    }
    """
    resp = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": {"login": user}},
        headers={"Authorization": f"bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    weeks = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    # grid[col][row] = contribution count, row 0 = Sunday
    grid = []
    for week in weeks:
        col = [0] * 7
        for day in week["contributionDays"]:
            col[day["weekday"]] = day["contributionCount"]
        grid.append(col)
    return grid


def bucket_levels(grid):
    """Map raw counts to 0-4 severity levels the same way GitHub roughly does,
    scaled to this user's own data range."""
    counts = sorted({c for col in grid for c in col if c > 0})
    if not counts:
        return [[0] * len(col) for col in grid]
    # quartile-ish thresholds
    import math
    n = len(counts)
    q1 = counts[max(0, math.ceil(n * 0.25) - 1)]
    q2 = counts[max(0, math.ceil(n * 0.50) - 1)]
    q3 = counts[max(0, math.ceil(n * 0.75) - 1)]

    def level(c):
        if c == 0:
            return 0
        if c <= q1:
            return 1
        if c <= q2:
            return 2
        if c <= q3:
            return 3
        return 4

    return [[level(c) for c in col] for col in grid]


def build_path(grid):
    """Boustrophedon (snake-pattern) scan across columns, keeping only
    cells with 0 contributions. This is the path the snake is allowed
    to walk on."""
    path = []
    for col_idx, col in enumerate(grid):
        rows = range(7) if col_idx % 2 == 0 else range(6, -1, -1)
        for row in rows:
            if col[row] == 0:
                path.append((col_idx, row))
    return path


def cell_xy(col, row):
    x = col * (CELL + GAP)
    y = row * (CELL + GAP)
    return x, y


def render_svg(grid, path, theme_name):
    theme = THEMES[theme_name]
    levels = bucket_levels(grid)
    n_cols = len(grid)
    width = n_cols * (CELL + GAP) - GAP
    height = 7 * (CELL + GAP) - GAP

    total_steps = max(1, len(path) - 1)
    total_duration = total_steps * STEP_DURATION

    svg_parts = []
    svg_parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}">'
    )
    svg_parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="{theme["bg"]}"/>')

    # background grid cells
    for col_idx, col in enumerate(grid):
        for row in range(7):
            x, y = cell_xy(col_idx, row)
            lvl = levels[col_idx][row]
            color = theme["levels"][lvl]
            svg_parts.append(
                f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" '
                f'rx="{RADIUS}" ry="{RADIUS}" fill="{color}"/>'
            )

    # build keyTimes / values strings for animateMotion-less approach:
    # animate x/y attributes directly per segment, each segment delayed
    # by one step behind the one in front of it.
    if len(path) >= 2:
        key_times = [round(i / total_steps, 4) for i in range(len(path))]
        key_times_str = ";".join(str(k) for k in key_times)

        for seg in range(SNAKE_LEN):
            # this segment's position sequence is the path, shifted back by `seg` steps
            xs, ys = [], []
            for i in range(len(path)):
                idx = max(0, i - seg)
                x, y = cell_xy(*path[idx])
                xs.append(str(x))
                ys.append(str(y))
            xs_str = ";".join(xs)
            ys_str = ";".join(ys)
            color = theme["snake_head"] if seg == 0 else theme["snake_body"]
            opacity = 1.0 if seg == 0 else max(0.35, 1 - seg * 0.15)
            svg_parts.append(
                f'<rect width="{CELL}" height="{CELL}" rx="{RADIUS}" ry="{RADIUS}" '
                f'fill="{color}" fill-opacity="{opacity:.2f}">'
                f'<animate attributeName="x" values="{xs_str}" keyTimes="{key_times_str}" '
                f'dur="{total_duration:.2f}s" repeatCount="indefinite" calcMode="discrete"/>'
                f'<animate attributeName="y" values="{ys_str}" keyTimes="{key_times_str}" '
                f'dur="{total_duration:.2f}s" repeatCount="indefinite" calcMode="discrete"/>'
                f'</rect>'
            )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--theme", choices=["light", "dark"], default="light")
    parser.add_argument("--mock", action="store_true", help="use fake data, skip API call")
    args = parser.parse_args()

    if args.mock:
        import random
        random.seed(7)
        grid = [[random.choice([0, 0, 0, 1, 2, 3, 5]) for _ in range(7)] for _ in range(53)]
    else:
        user = os.environ["GITHUB_USER"]
        token = os.environ["GITHUB_TOKEN"]
        grid = fetch_contributions(user, token)

    path = build_path(grid)
    svg = render_svg(grid, path, args.theme)

    with open(args.output, "w") as f:
        f.write(svg)
    print(f"Wrote {args.output} | {len(path)} walkable (0-contribution) cells out of {len(grid)*7}")


if __name__ == "__main__":
    main()
