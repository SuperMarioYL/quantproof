#!/usr/bin/env python3
"""Render QuantProof presentation artwork from authored facts and the renderer palette.

Reads docs/presentation.json + web/palette.json + web/site.json + docs/demo-results.json,
writes the four animated light/dark SVG groups (hero, architecture, process,
integrations) plus mobile variants, the static scene fallback and per-step demo
panels into assets/presentation/ and web/assets/presentation/. Every SVG uses
self-contained CSS animation (no script), keeps a complete static frame, stops
decorative motion under prefers-reduced-motion, and stamps the palette id as
data-palette so the shared presentation validator can detect stale exports.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import shutil
from html import escape
from pathlib import Path

FONT = "font-family:Arial,'Helvetica Neue','Noto Sans',sans-serif"
MONO = "font-family:Menlo,Consolas,'Liberation Mono',monospace"


def text_of(value) -> str:
    """Localized {zh,en} pairs resolve to the English primary."""
    if isinstance(value, dict):
        return str(value.get("en") or value.get("zh") or "")
    return str(value or "")


class Pen:
    """Small drawing helper bound to one palette mode."""

    def __init__(self, palette: dict, mode: str) -> None:
        self.p = palette[mode]
        self.id = palette["id"]

    def color(self, name: str) -> str:
        return self.p[name]

    def txt(self, x, y, s, size=18, color="ink", anchor="start", weight=400, mono=False):
        family = MONO if mono else FONT
        return (
            f'<text x="{x:.1f}" y="{y:.1f}" fill="{self.color(color)}" font-size="{size}" '
            f'text-anchor="{anchor}" font-weight="{weight}" style="{family}">{escape(text_of(s))}</text>'
        )

    def para(self, x, y, s, width, size=17, color="muted", limit=3, anchor="start", lheight=1.45):
        chars = max(8, int(width / (size * 0.52)))
        rows: list[str] = []
        for word in text_of(s).split():
            if rows and len(rows[-1]) + len(word) + 1 <= chars:
                rows[-1] += " " + word
            else:
                rows.append(word)
        if len(rows) > limit:
            rows = rows[:limit]
            rows[-1] = rows[-1].rstrip(".,") + "…"
        return "".join(
            self.txt(x, y + i * size * lheight, row, size, color, anchor) for i, row in enumerate(rows)
        )

    def card(self, x, y, w, h, title, detail, detail_size=13.5):
        body = (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12" '
            f'fill="{self.color("panel")}" stroke="{self.color("line")}"/>'
        )
        body += self.txt(x + 16, y + 27, title, 18, "ink", weight=600)
        body += self.para(x + 16, y + 54, detail, w - 32, detail_size, "muted", 3)
        return body

    def chip(self, x, y, label, fill, stroke):
        w = max(64, 12 + len(text_of(label)) * 7.6)
        return (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="24" rx="12" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="0.8" opacity="0.92"/>'
            + self.txt(x + w / 2, y + 16.5, label, 12.5, "ink", anchor="middle", weight=600)
        )

    def flow(self, d, width=1.6, color_name="primary"):
        """Animated dashed connector; under reduced motion it stays a dashed line."""
        return (
            f'<path d="{d}" fill="none" stroke="{self.color("line")}" stroke-width="{width + 0.6}"/>'
            f'<path class="qp-flow" d="{d}" fill="none" stroke="{self.color(color_name)}" '
            f'stroke-width="{width}" stroke-dasharray="7 11"/>'
        )

    def arrow(self, d, color_name="primary"):
        return (
            f'<path d="{d}" fill="none" stroke="{self.color(color_name)}" stroke-width="1.6" '
            f'marker-end="url(#qp-arrow)"/>'
        )

    def particles(self, cx, cy, rx, ry, count, seed, slow=False):
        rng = random.Random(seed)
        dots = []
        for i in range(count):
            angle = rng.random() * math.tau
            z = rng.uniform(-1, 1)
            r = math.sqrt(1 - z * z)
            x = cx + rx * r * math.cos(angle)
            y = cy + ry * z
            color = "primary" if i % 3 else "secondary"
            dots.append(
                f'<circle class="{"qp-drift-slow" if slow else "qp-drift"}" cx="{x:.1f}" cy="{y:.1f}" '
                f'r="{rng.uniform(0.7, 1.9):.2f}" fill="{self.color(color)}" '
                f'opacity="{rng.uniform(0.25, 0.85):.2f}"/>'
            )
        return "".join(dots)

    def style(self):
        css = (
            "text{"
            + FONT
            + "}.qp-mono{"
            + MONO
            + "}.qp-flow{animation:qp-flow 5.5s linear infinite}"
            "@keyframes qp-flow{to{stroke-dashoffset:-180}}"
            ".qp-pulse{animation:qp-pulse 4.2s ease-in-out infinite}"
            "@keyframes qp-pulse{0%,100%{opacity:.45}50%{opacity:1}}"
            ".qp-drift{animation:qp-drift 9s ease-in-out infinite}"
            ".qp-drift-slow{animation:qp-drift 16s ease-in-out infinite}"
            "@keyframes qp-drift{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}"
            ".qp-breathe{animation:qp-pulse 6.5s ease-in-out infinite}"
            "@media (prefers-reduced-motion: reduce){*{animation:none !important;transform:none !important}}"
        )
        return f"<style>{css}</style>"

    def svg_open(self, w, h, title, desc):
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'data-palette="{self.id}" role="img" aria-labelledby="qp-title qp-desc">'
            f'<title id="qp-title">{escape(title)}</title><desc id="qp-desc">{escape(desc)}</desc>'
        )

    def backdrop(self, w, h, grid=44):
        return (
            f'<rect width="{w}" height="{h}" rx="14" fill="{self.color("bg")}"/>'
            f'<pattern id="qp-grid" width="{grid}" height="{grid}" patternUnits="userSpaceOnUse">'
            f'<path d="M{grid} 0H0V{grid}" fill="none" stroke="{self.color("line")}" '
            f'stroke-opacity="0.32" stroke-width="0.6"/></pattern>'
            f'<rect width="{w}" height="{h}" rx="14" fill="url(#qp-grid)"/>'
            f'<radialGradient id="qp-halo" cx="0.62" cy="0.42" r="0.75">'
            f'<stop stop-color="{self.color("primary")}" stop-opacity="0.16"/>'
            f'<stop offset="1" stop-color="{self.color("bg")}" stop-opacity="0"/></radialGradient>'
            f'<rect width="{w}" height="{h}" rx="14" fill="url(#qp-halo)"/>'
            f'<linearGradient id="qp-brand" x1="0" y1="0" x2="1" y2="1">'
            f'<stop stop-color="{self.color("primary")}"/>'
            f'<stop offset="0.55" stop-color="{self.color("secondary")}"/>'
            f'<stop offset="1" stop-color="{self.color("highlight")}"/></linearGradient>'
            f'<marker id="qp-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" '
            f'markerHeight="5" orient="auto"><path d="m1 1 7 4-7 4" fill="none" '
            f'stroke="{self.color("primary")}" stroke-width="1.5"/></marker>'
        )


def render_hero(pen: Pen, facts: dict, mobile: bool):
    """Particle convergence into a ranked-bars motif: the collapse delta at a glance."""
    w, h = (400, 500) if mobile else (1000, 400)
    bars = facts["hero_bars"]

    # Atmosphere first, then text on top, then the bar block.
    atmosphere = ""
    if not mobile:
        atmosphere += pen.particles(290, 240, 190, 120, 240, facts["name"] + "-hero", slow=True)
        atmosphere += pen.flow("M470 300C560 260,520 210,582 190")

    text = pen.txt(30 if mobile else 52, 52 if mobile else 58, "LOCAL QUANT CALIBRATION · MIT", 13, "muted")
    size = min(52 if mobile else 64, (330 if mobile else 560) / max(1, len(facts["name"])) / 0.62)
    text += (
        f'<text x="{30 if mobile else 52}" y="{112 if mobile else 130}" font-size="{size:.1f}" '
        f'fill="url(#qp-brand)" font-weight="700" style="{FONT}">{escape(facts["name"])}</text>'
    )
    text += pen.para(
        30 if mobile else 54, 156 if mobile else 182, facts["tagline"], 336 if mobile else 470,
        18 if mobile else 20, "ink", 3,
    )

    bar_block = ""
    bx = 34 if mobile else 590
    bw = 332 if mobile else 380
    by = 236 if mobile else 150
    row_h = 76 if mobile else 64
    bar_block += pen.txt(bx, by - 24, "PASS RATE ON YOUR TASKS", 12.5, "muted")
    for i, bar in enumerate(bars):
        y = by + i * row_h
        rate = float(bar["rate"])
        collapsed = "collapse" in text_of(bar["note"])
        fill = pen.color("highlight") if collapsed else pen.color("primary")
        bar_block += pen.txt(bx, y + 14, bar["label"], 16, "ink", weight=600)
        bar_block += pen.txt(bx + bw, y + 14, bar["note"], 13.5, "highlight" if collapsed else "muted", anchor="end")
        track_y = y + 26
        bar_block += (
            f'<rect x="{bx}" y="{track_y}" width="{bw}" height="12" rx="6" fill="{pen.color("panel")}" '
            f'stroke="{pen.color("line")}" stroke-width="0.7"/>'
        )
        fill_w = max(10.0, bw * rate / 100.0)
        bar_block += (
            f'<rect class="qp-pulse" x="{bx}" y="{track_y}" width="{fill_w:.1f}" height="12" rx="6" '
            f'fill="{fill}" opacity="{0.9 if collapsed else 0.8}"/>'
        )
        if collapsed:
            bar_block += pen.chip(bx + bw - 74, track_y + 22, "collapse", pen.color("highlight"), pen.color("line"))
        else:
            bar_block += pen.txt(bx + bw, track_y + 38, f"{rate:.0f}%", 13, "muted", anchor="end")

    note = facts.get("hero_note", "")
    return (
        atmosphere + text + bar_block,
        w,
        h,
        f"{facts['name']} — ranked on your tasks",
        f"Illustrative pass-rate bars for quant variants with the collapse delta; {note}",
    )


def render_architecture(pen: Pen, facts: dict, mobile: bool):
    """Layered blueprint: inputs, the four modules, the llama-server child, the output."""
    arch = facts["architecture"]
    w = 400 if mobile else 1000
    body = pen.txt(28 if mobile else 48, 46, "ARCHITECTURE / DATA FLOW", 13, "muted")
    body += pen.para(28 if mobile else 48, 82, arch["title"], 344 if mobile else 900, 26 if mobile else 30, "ink", 2)

    if mobile:
        h = 0
        y = 130
        for inp in arch["inputs"]:
            body += pen.card(28, y, 344, 92, inp["title"], inp["detail"])
            y += 104
        body += pen.flow(f"M200 {y - 12}V{y + 10}")
        y += 14
        node_h = 118
        for i, node in enumerate(arch["nodes"]):
            body += pen.card(28, y, 344, node_h, node["title"], node["detail"])
            if i == 1:  # runner owns the llama-server child
                body += pen.card(70, y + node_h + 8, 260, 96, arch["child"]["title"], arch["child"]["detail"], 13)
                body += pen.flow(f"M200 {y + node_h}V{y + node_h + 8}", 1.2, "secondary")
                y += 104
            if i < len(arch["nodes"]) - 1:
                body += pen.flow(f"M200 {y + node_h}V{y + node_h + 24}")
            y += node_h + 24
        body += pen.card(28, y, 344, 96, arch["output"]["title"], arch["output"]["detail"], 13)
        h = y + 96 + 26
    else:
        h = 570
        body += pen.txt(48, 150, "INPUTS", 12, "muted")
        body += pen.card(48, 160, 176, 96, arch["inputs"][0]["title"], arch["inputs"][0]["detail"], 13)
        body += pen.card(48, 268, 176, 96, arch["inputs"][1]["title"], arch["inputs"][1]["detail"], 13)
        body += pen.arrow("M224 208H262")

        body += pen.txt(268, 150, "MODULES (one CLI process)", 12, "muted")
        xs = [268, 450, 632, 814]
        card_w = 168
        for node, x in zip(arch["nodes"], xs, strict=True):
            body += pen.card(x, 160, card_w, 132, node["title"], node["detail"], 13)
        for i in range(len(xs) - 1):
            body += pen.arrow(f"M{xs[i] + card_w} 226H{xs[i + 1] - 5}")

        # The single llama-server child hangs off runner.
        body += pen.card(450, 322, 168, 96, arch["child"]["title"], arch["child"]["detail"], 13)
        body += pen.flow("M534 292V322", 1.2, "secondary")
        body += pen.card(766, 322, 216, 96, arch["output"]["title"], arch["output"]["detail"], 13)
        body += pen.arrow("M898 292V322")

        body += pen.para(
            48, 464,
            "state is files on disk: the task pack in, the ranked table out — no daemon, no "
            "database, at most two processes alive (this CLI and one llama-server child).",
            880, 16.5, "muted", 3,
        )
        body += pen.particles(856, 470, 112, 44, 130, facts["name"] + "-arch")
    return body, w, h, f"{facts['name']} architecture", text_of(arch["title"])


def render_process(pen: Pen, facts: dict, mobile: bool):
    """The per-variant loop with the load step outside it and the ranked result as a footer."""
    proc = facts["process"]
    steps = proc["steps"]
    w = 400 if mobile else 1000
    body = pen.txt(28 if mobile else 48, 46, "PROCESS / FROM PACK TO VERDICT", 13, "muted")
    body += pen.para(28 if mobile else 48, 82, proc["title"], 344 if mobile else 900, 26 if mobile else 30, "ink", 2)

    if mobile:
        y = 128
        body += pen.card(28, y, 344, 112, f"01  {steps[0]['title']}", steps[0]["detail"])
        y += 124
        loop_top = y
        for i, step in enumerate(steps[1:], start=2):
            body += pen.card(28, y, 344, 112, f"{i:02d}  {step['title']}", step["detail"])
            if i < len(steps):
                body += pen.flow(f"M200 {y + 112}V{y + 132}")
            y += 132
        body += pen.flow(f"M372 {loop_top + 56}H388V{y - 56}H372", 1.2, "secondary")
        body += pen.txt(200, y - 6, proc["loop_label"], 13, "muted", anchor="middle")
        y += 16
        body += pen.card(28, y, 344, 112, "result", proc["result"], 14)
        h = y + 124
    else:
        body += pen.card(48, 150, 158, 132, f"01  {steps[0]['title']}", steps[0]["detail"], 13.5)
        body += pen.arrow("M206 216H250")
        loop_x, loop_y, loop_w, loop_h = 254, 140, 698, 162
        body += (
            f'<rect x="{loop_x}" y="{loop_y}" width="{loop_w}" height="{loop_h}" rx="16" fill="none" '
            f'stroke="{pen.color("line")}" stroke-dasharray="3 7"/>'
        )
        body += pen.txt(loop_x + 14, loop_y + 22, proc["loop_label"].upper(), 11.5, "muted")
        cw = (loop_w - 28 - 3 * 14) / 4
        for i, step in enumerate(steps[1:], start=2):
            x = loop_x + 14 + (i - 2) * (cw + 14)
            body += pen.card(x, loop_y + 32, cw, 112, f"{i:02d}  {step['title']}", step["detail"], 12.5)
            if i - 2 < 3:
                body += pen.arrow(f"M{x + cw} {loop_y + 88}H{x + cw + 14}")
        # Return edge: swap-the-variant loops back to start-server.
        body += pen.flow(
            f"M{loop_x + loop_w - cw / 2} {loop_y + loop_h}V{loop_y + loop_h + 26}"
            f"H{loop_x + cw / 2}V{loop_y + loop_h}",
            1.2,
            "secondary",
        )
        body += (
            f'<rect x="48" y="366" width="904" height="72" rx="12" fill="{pen.color("panel")}" '
            f'stroke="{pen.color("highlight")}" stroke-width="0.9"/>'
        )
        body += pen.txt(66, 390, "RESULT", 12, "muted")
        body += pen.para(66, 414, proc["result"], 860, 16, "ink", 2)
        body += pen.particles(888, 100, 95, 28, 80, facts["name"] + "-proc")
        h = 470
    return body, w, h, f"{facts['name']} calibration loop", text_of(proc["result"])


def render_integrations(pen: Pen, facts: dict, mobile: bool):
    """Hub-and-spoke: the task pack at the center, what plugs in around it."""
    integ = facts["integrations"]
    items = integ["items"]
    hub = integ["hub"]
    w = 400 if mobile else 1000

    if mobile:
        h = 262 + len(items) * 82
        body = pen.txt(28, 46, "CAPABILITIES / CONNECTIONS", 13, "muted")
        body += pen.para(28, 82, integ["title"], 344, 26, "ink", 2)
        body += (
            f'<circle cx="200" cy="176" r="62" fill="{pen.color("panel")}" '
            f'stroke="{pen.color("primary")}" stroke-width="1.4"/>'
        )
        body += pen.txt(200, 170, hub["title"], 14, "primary", anchor="middle", weight=600)
        body += pen.para(200, 190, hub["detail"], 112, 11.5, "muted", 2, anchor="middle")
        y = 262
        for item in items:
            body += pen.flow(f"M200 238V{y}", 1.1)
            body += pen.card(28, y, 344, 70, item["title"], item["detail"], 13)
            y += 82
    else:
        h = 668
        body = pen.txt(48, 46, "CAPABILITIES / CONNECTIONS", 13, "muted")
        body += pen.para(48, 82, integ["title"], 900, 30, "ink", 2)
        cx, cy = 500, 348
        body += (
            f'<ellipse cx="{cx}" cy="{cy}" rx="252" ry="152" fill="none" stroke="{pen.color("line")}" '
            f'stroke-dasharray="2 8"/>'
            f'<circle class="qp-breathe" cx="{cx}" cy="{cy}" r="78" fill="{pen.color("panel")}" '
            f'stroke="{pen.color("primary")}" stroke-width="1.4"/>'
        )
        body += pen.txt(cx, cy - 2, hub["title"], 16.5, "primary", anchor="middle", weight=600)
        body += pen.para(cx, cy + 20, hub["detail"], 140, 12.5, "muted", 2, anchor="middle")
        slots = [(140, 152), (140, 344), (140, 536), (706, 152), (706, 344), (706, 536)]
        for item, (x, y) in zip(items, slots, strict=True):
            left = x < cx
            start_x = x + 236 if left else x
            end_x = cx - 78 if left else cx + 78
            start_y = y + 48
            end_y = cy - 42 if y < cy else cy + 42
            body += pen.flow(f"M{start_x} {start_y}L{end_x} {end_y}", 1.1)
            body += pen.card(x, y, 236, 96, item["title"], item["detail"], 13)
    return body, w, h, f"{facts['name']} — what plugs in today", text_of(integ["title"])


def render_scene(pen: Pen, facts: dict):
    """Genuinely static fallback scene — no animation even without reduced-motion."""
    w, h = 1000, 700
    body = pen.particles(500, 330, 430, 250, 1500, facts["name"] + "-scene")
    body += pen.flow("M180 420L400 300L560 352L780 240", 1.2)
    body += pen.txt(500, 660, facts["name"], 20, "muted", anchor="middle")
    return body, w, h, f"{facts['name']} particle scene", "Static particle field; no result is represented."


def render_demo_panel(pen: Pen, facts: dict, site: dict, record: dict, index: int):
    step = site["demo"]["steps"][index]
    w, h = 760, 330
    body = pen.txt(36, 46, f"DEMO / STEP {index + 1:02}", 13, "muted")
    body += pen.para(36, 90, step["label"], 660, 27, "ink", 2)
    body += pen.para(36, 148, step["body"], 660, 18, "muted", 3)
    body += f'<path d="M36 234H724" stroke="{pen.color("line")}"/>'
    body += pen.para(36, 272, record["steps"][index]["command"], 660, 15.5, "primary", 3, lheight=1.5)
    return body, w, h, f"{facts['name']} demo step {index + 1}", text_of(step["body"])


def save(repo: Path, name: str, pen: Pen, body: str, w: int, h: int, title: str, desc: str) -> None:
    svg = pen.svg_open(w, h, title, desc) + pen.backdrop(w, h) + pen.style() + body + "</svg>\n"
    out = repo / "assets/presentation" / f"{name}.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    web = repo / "web/assets/presentation" / f"{name}.svg"
    web.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, web)


def stamp_icons(repo: Path, palette: dict) -> None:
    """Recolor the tabler section icons from the palette and stamp data-palette.

    The icons are static tabler outlines; their only palette-derived property
    is the stroke color, so they are restamped here alongside the artwork to
    keep every README-referenced SVG tied to the same palette revision.
    """
    for icon in sorted((repo / "assets/icons").glob("*.svg")):
        svg = icon.read_text(encoding="utf-8")
        svg = re.sub(r'stroke="#[0-9a-fA-F]{6}"', f'stroke="{palette["primary"]}"', svg, count=1)
        if 'data-palette="' in svg:
            svg = re.sub(r'data-palette="[^"]*"', f'data-palette="{palette["id"]}"', svg)
        else:
            svg = svg.replace("<svg ", f'<svg data-palette="{palette["id"]}" ', 1)
        icon.write_text(svg, encoding="utf-8")


def render(repo: Path) -> None:
    facts = json.loads((repo / "docs/presentation.json").read_text())
    palette = json.loads((repo / "web/palette.json").read_text())
    site = json.loads((repo / "web/site.json").read_text())
    record = json.loads((repo / "docs/demo-results.json").read_text())
    stamp_icons(repo, palette)
    for mode in ("dark", "light"):
        pen = Pen(palette, mode)
        for mobile in (False, True):
            for kind, fn in (
                ("hero", render_hero),
                ("architecture", render_architecture),
                ("process", render_process),
                ("integrations", render_integrations),
            ):
                body, w, h, title, desc = fn(pen, facts, mobile)
                save(repo, f"{kind}{'-mobile' if mobile else ''}-{mode}", pen, body, w, h, title, desc)
        body, w, h, title, desc = render_scene(pen, facts)
        save(repo, f"scene-{mode}", pen, body, w, h, title, desc)
        for index in range(len(site["demo"]["steps"])):
            body, w, h, title, desc = render_demo_panel(pen, facts, site, record, index)
            save(repo, f"demo-{index}-{mode}", pen, body, w, h, title, desc)
    print(f"{facts['name']}: SVG groups generated with palette {palette['id']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    render(parser.parse_args().repo.resolve())
