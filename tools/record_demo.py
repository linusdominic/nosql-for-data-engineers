"""Record the lesson studio's demo video, end to end.

    make demo-video      (needs Google Chrome, ffmpeg with libx264, and every database:
                          make up-capstone up-05)

Writes:

    docs/media/studio-demo.mp4         1920x1080, 30 fps, H.264 + AAC, about 3 minutes
    docs/media/studio-demo-poster.png  the title still, 1920x1080
    docs/img/studio-demo-poster.jpg    the same still at 1280x720 with a play button, for the README
    docs/img/studio-demo.gif           a short loop: exercise 2.3 from typed answer to PASS

Playwright is not a project dependency: the make target runs this file with
`uv run --with playwright==1.56.0` and drives the installed Chrome (channel "chrome").

How it works:

* It starts its own studio on --port (default 8792) with a random token and the progress
  file in a scratch folder (--work), so a running `make studio` and the repository's
  .studio/progress.json are never touched. The token never appears in the video.
* Before recording it prepares chapters 2 to 6 and checks a few reference solutions
  through the studio's own API, so the progress rings show a learner partway through.
  These are real checks against the databases, not edited progress.
* Chrome runs headless at 1536x864 CSS pixels with deviceScaleFactor 1.25, which is
  1920x1080 device pixels: the studio is drawn at full resolution and its text is a
  little larger than at 1920 CSS pixels, so it reads well on a laptop. Frames come from
  CDP Page.startScreencast (JPEG quality 95) and are turned into a constant 30 fps
  stream by their timestamps, so every clip runs in real time.
* A cursor, click ripples and captions are drawn by a small overlay added with
  add_init_script and driven with page.evaluate. It uses the CSSOM only, so the studio's code and its
  Content-Security-Policy are left exactly as they are.
* The title, install and closing cards are HTML pages written to the work folder. The
  install scene types the real commands; their output was captured from real runs
  (INSTALL below, abridged) and the `make studio` address shows a placeholder token.
* ffmpeg joins the clips with short crossfades, adds a quiet music bed (CC0, see
  --music) normalised to -24 LUFS with fades, and cuts the GIF from the exercise clip.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import html
import json
import math
import os
import queue
import random
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FPS = 30
VIEW_W, VIEW_H, SCALE = 1536, 864, 1.25  # CSS pixels; 1920x1080 device pixels
OUT_W, OUT_H = 1920, 1080
REPO_URL = "https://github.com/linusdominic/nosql-for-data-engineers"
EXPLORER_URL = "https://linusdominic.github.io/nosql-for-data-engineers/explorer/"
DEFAULT_MUSIC = Path.home() / "Documents" / "reel-studio" / "music" / "softly.m4a"
TOKEN_ENV = "NOSQLDE_DEMO_TOKEN"
COLOR = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
# Chrome's JPEG frames are full-range BT.601; video players expect limited-range BT.709.
TO_VIDEO = "in_range=full:out_range=limited:in_color_matrix=bt601:out_color_matrix=bt709"
TARGET_LUFS = -24.0

# Exercises passed (with their reference solutions) before recording, so the rings show
# a learner partway through. Exercise 2.3 is left for the video.
SEED_PASSES = (
    "ch02.lookup",
    "ch02.collscan",
    "ch03.",  # the first exercises of a chapter: see seed_progress
    "ch04.",
    "ch05.",
)
SEED_COUNTS = {"ch03.": 4, "ch04.": 3, "ch05.": 2}

# ---------------------------------------------------------------------------------
# The install scene. Each command was run for real and its output captured (git clone of
# the public repository into an empty folder, make setup in that clone, make up-capstone
# up-05 with the databases already running, make studio); the output is abridged ("...")
# and the token in the studio address is a placeholder.
INSTALL: list[dict[str, Any]] = [
    {
        "cwd": "~",
        "cmd": f"git clone {REPO_URL}.git",
        "step": 0,
        "caption": "Clone the repository",
        "out": [
            "Cloning into 'nosql-for-data-engineers'...",
            "remote: Enumerating objects: 248, done.",
            "remote: Counting objects: 100% (248/248), done.",
            "remote: Compressing objects: 100% (178/178), done.",
            "remote: Total 248 (delta 67), reused 242 (delta 61), pack-reused 0 (from 0)",
            "Receiving objects: 100% (248/248), 2.19 MiB | 4.36 MiB/s, done.",
            "Resolving deltas: 100% (67/67), done.",
        ],
    },
    {"cwd": "~", "cmd": "cd nosql-for-data-engineers", "step": 0, "out": []},
    {
        "cwd": "~/nosql-for-data-engineers",
        "cmd": "make setup",
        "step": 1,
        "caption": "make setup installs Python 3.12 and the pinned packages with uv",
        "out": [
            "uv sync --python 3.12",
            "Using CPython 3.12.16",
            "Creating virtual environment at: .venv",
            "Resolved 50 packages in 17ms",
            "Installed 49 packages in 176ms",
            " + boto3==1.44.6",
            " + cassandra-driver==3.30.1",
            " + duckdb==2.0.0",
            " + fastapi==0.162.0",
            " + neo4j==6.4.1",
            " + pymongo==4.20.0",
            " + redis==8.1.0",
            "   ...",
            "",
            "Setup done. Next: read guide/00-setup.md, then run 'make check-01'.",
        ],
    },
    {
        "cwd": "~/nosql-for-data-engineers",
        "cmd": "make up-capstone up-05",
        "step": 2,
        "caption": "Start the databases in Docker: these two targets start all five",
        "out": [
            "docker compose --profile capstone up -d --wait",
            " Container nosqlde-mongo-1      Healthy",
            " Container nosqlde-redis-1      Healthy",
            " Container nosqlde-cassandra-1  Healthy",
            " Container nosqlde-neo4j-1      Healthy",
            "docker compose --profile ch05 up -d --wait",
            " Container nosqlde-dynamodb-1   Healthy",
        ],
    },
    {
        "cwd": "~/nosql-for-data-engineers",
        "cmd": "make studio",
        "step": 3,
        "caption": "make studio prints the address to open in your browser",
        "out": [
            "uv run --python 3.12 nosqlde studio --port 8790",
            "NoSQL lesson studio",
            "  open @@URL@@",
            "  (the token changes every start; the server listens on 127.0.0.1 only. Ctrl+C stops it.)",
        ],
    },
]
INSTALL_STEPS = ("Clone", "Set up", "Start the databases", "Start the studio")
STUDIO_URL_SHOWN = "http://127.0.0.1:8790/?token=…"

# ---------------------------------------------------------------------------------
# The overlay: cursor, click ripple and captions, drawn with the CSSOM only.
OVERLAY_JS = r"""
(() => {
  if (window.__demo) return;
  const NS = "http://www.w3.org/2000/svg";
  const css = (el, props) => { for (const k in props) el.style.setProperty(k, props[k]); return el; };
  const st = { x: 760, y: 520, root: null, cursor: null, cap: null, capKicker: null, capText: null, shown: false };
  function ensure() {
    if (st.root && st.root.isConnected) return;
    const root = css(document.createElement("div"), { position: "fixed", inset: "0", "pointer-events": "none", "z-index": "2147483647" });
    root.setAttribute("aria-hidden", "true");
    const cur = document.createElementNS(NS, "svg");
    cur.setAttribute("width", "28"); cur.setAttribute("height", "28"); cur.setAttribute("viewBox", "0 0 28 28");
    css(cur, { position: "absolute", left: "0", top: "0", overflow: "visible", opacity: "0",
      filter: "drop-shadow(0 2px 3px rgba(0,0,0,0.35))", "transform-origin": "3px 2px", "will-change": "transform" });
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", "M3 2 L3 21.5 L8 16.9 L11.3 24.6 L14.9 23 L11.6 15.5 L18.4 15.5 Z");
    p.setAttribute("fill", "#0e1d18"); p.setAttribute("stroke", "#ffffff"); p.setAttribute("stroke-width", "1.7");
    p.setAttribute("stroke-linejoin", "round");
    cur.appendChild(p);
    const cap = css(document.createElement("div"), { position: "absolute", bottom: "54px", left: "50%",
      transform: "translateX(-50%)", "max-width": "min(880px, 80vw)", opacity: "0", display: "flex",
      "flex-direction": "column", gap: "3px", padding: "13px 24px 14px 20px", "border-radius": "12px",
      background: "rgba(11, 44, 34, 0.96)", color: "#f1f7f4", "border-left": "4px solid #00e26b",
      "box-shadow": "0 12px 32px rgba(4, 21, 13, 0.32), 0 2px 6px rgba(4, 21, 13, 0.2)",
      "font-family": 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' });
    const kick = css(document.createElement("div"), { "font-size": "12.5px", "font-weight": "700", "letter-spacing": "0.08em",
      "text-transform": "uppercase", color: "#00e26b" });
    const text = css(document.createElement("div"), { "font-size": "20px", "font-weight": "600", "line-height": "1.35", "letter-spacing": "0.005em" });
    cap.appendChild(kick); cap.appendChild(text);
    root.appendChild(cap); root.appendChild(cur);
    document.documentElement.appendChild(root);
    st.root = root; st.cursor = cur; st.cap = cap; st.capKicker = kick; st.capText = text;
    place();
  }
  function place() { st.cursor.style.setProperty("transform", "translate(" + st.x + "px," + st.y + "px)"); }
  const ease = (t) => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  function frame(dur, step) {
    return new Promise((resolve) => {
      const t0 = performance.now();
      function tick(now) {
        const t = Math.min(1, (now - t0) / dur);
        step(ease(t));
        if (t < 1) requestAnimationFrame(tick); else resolve();
      }
      requestAnimationFrame(tick);
    });
  }
  const api = {
    show() { ensure(); st.cursor.style.setProperty("opacity", "1"); },
    hide() { ensure(); st.cursor.style.setProperty("opacity", "0"); },
    jump(x, y) { ensure(); st.x = x; st.y = y; place(); },
    async move(x, y, ms) {
      ensure();
      const x0 = st.x, y0 = st.y;
      const dist = Math.hypot(x - x0, y - y0);
      if (dist < 1) return;
      const dur = ms || Math.max(420, Math.min(1050, 300 + dist * 0.55));
      // a slight arc, as a hand moves
      const nx = -(y - y0) / dist, ny = (x - x0) / dist, bend = Math.min(40, dist * 0.08);
      await frame(dur, (e) => {
        const arc = Math.sin(Math.PI * e) * bend;
        st.x = x0 + (x - x0) * e + nx * arc; st.y = y0 + (y - y0) * e + ny * arc; place();
      });
      st.x = x; st.y = y; place();
    },
    async click(color) {
      ensure();
      const ring = css(document.createElement("div"), { position: "absolute", left: (st.x - 22) + "px", top: (st.y - 22) + "px",
        width: "44px", height: "44px", "border-radius": "50%", border: "2.5px solid " + (color || "#00b85a"),
        background: "rgba(0, 226, 107, 0.16)", "box-sizing": "border-box" });
      st.root.insertBefore(ring, st.cursor);
      const a = ring.animate([{ transform: "scale(0.3)", opacity: 0.9 }, { transform: "scale(1.25)", opacity: 0 }], { duration: 560, easing: "cubic-bezier(.2,.7,.3,1)" });
      a.onfinish = () => ring.remove();
      await frame(110, (e) => { st.cursor.style.setProperty("transform", "translate(" + st.x + "px," + st.y + "px) scale(" + (1 - 0.16 * e) + ")"); });
      await frame(150, (e) => { st.cursor.style.setProperty("transform", "translate(" + st.x + "px," + st.y + "px) scale(" + (0.84 + 0.16 * e) + ")"); });
      place();
    },
    async caption(text, kicker, where) {
      ensure();
      const cap = st.cap;
      if (st.shown) {
        await cap.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 220, fill: "forwards" }).finished;
      }
      st.capKicker.textContent = kicker || "";
      st.capKicker.style.setProperty("display", kicker ? "block" : "none");
      st.capText.textContent = text;
      // centre it over the lesson (left), the console (right) or the page, inside the window
      const frac = where === "left" ? 0.2 : where === "right" ? 0.72 : 0.5;
      cap.style.setProperty("left", "0px");
      const vw = document.documentElement.clientWidth, w = cap.offsetWidth;
      const cx = Math.max(w / 2 + 18, Math.min(vw - w / 2 - 18, frac * vw));
      cap.style.setProperty("left", cx + "px");
      cap.style.setProperty("bottom", where === "high" ? "auto" : "54px");
      cap.style.setProperty("top", where === "high" ? "122px" : "auto");
      cap.getAnimations().forEach((a) => a.cancel());
      cap.style.setProperty("opacity", "1");
      st.shown = true;
      await cap.animate([{ opacity: 0, transform: "translateX(-50%) translateY(10px)" }, { opacity: 1, transform: "translateX(-50%) translateY(0)" }],
        { duration: 340, easing: "cubic-bezier(.2,.7,.3,1)" }).finished;
    },
    async uncaption() {
      ensure();
      if (!st.shown) return;
      st.shown = false;
      await st.cap.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 260, fill: "forwards" }).finished;
      st.cap.getAnimations().forEach((a) => a.cancel());
      st.cap.style.setProperty("opacity", "0");
    },
    // Scroll the nearest scrollable ancestor of el so that el's top sits `offset` px below
    // the container's top, with an eased animation.
    async scrollTo(el, offset, ms) {
      let box = el.parentElement;
      while (box && box !== document.body) {
        const s = getComputedStyle(box);
        if (/(auto|scroll)/.test(s.overflowY) && box.scrollHeight > box.clientHeight) break;
        box = box.parentElement;
      }
      if (!box || box === document.body) box = document.scrollingElement;
      const from = box.scrollTop;
      const top = el.getBoundingClientRect().top - (box === document.scrollingElement ? 0 : box.getBoundingClientRect().top);
      const to = Math.max(0, Math.min(box.scrollHeight - box.clientHeight, from + top - offset));
      if (Math.abs(to - from) < 2) return;
      const dur = ms || Math.max(500, Math.min(1200, Math.abs(to - from) * 0.9));
      box.style.setProperty("scroll-behavior", "auto");
      await frame(dur, (e) => { box.scrollTop = from + (to - from) * e; });
      box.style.removeProperty("scroll-behavior");
    },
  };
  window.__demo = api;
})();
"""

# ---------------------------------------------------------------------------------
# Cards: the title, the install terminal and the closing card. System fonts, the studio's
# colours (src/nosqlde/studio/static/DESIGN.md).
CARD_CSS = """
:root { --chrome: #0b2c22; --chrome-2: #103a2d; --line: #22493b; --fg: #f1f7f4; --muted: #a8c3b7;
  --spring: #00e26b; --mongo: #00e26b; --redis: #ff6a5c; --cass: #4cb8da; --dynamo: #ff9a1f; --neo: #7fd8e0; --duck: #fff100;
  --sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --display: ui-serif, "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace; }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body { background: radial-gradient(1200px 700px at 78% 30%, #134a39 0%, var(--chrome) 55%, #071d16 100%);
  color: var(--fg); font-family: var(--sans); overflow: hidden; -webkit-font-smoothing: antialiased; }
.mark { display: inline-flex; align-items: flex-end; gap: 5px; height: 40px; }
.mark i { display: block; width: 8px; border-radius: 4px; }
.mark i:nth-child(1) { height: 40px; background: var(--mongo); }
.mark i:nth-child(2) { height: 29px; background: var(--redis); }
.mark i:nth-child(3) { height: 22px; background: var(--cass); }
.mark i:nth-child(4) { height: 33px; background: var(--dynamo); }
.mark i:nth-child(5) { height: 18px; background: var(--neo); }
.chips { display: flex; flex-wrap: wrap; gap: 10px; }
.chip { display: inline-flex; align-items: center; gap: 8px; padding: 6px 13px; border-radius: 999px;
  border: 1px solid var(--line); background: rgba(16, 58, 45, 0.7); font-size: 15px; font-weight: 600; }
.chip b { width: 9px; height: 9px; border-radius: 50%; display: block; }
.up { opacity: 0; transform: translateY(14px); animation: up 0.7s cubic-bezier(.2,.7,.3,1) forwards; }
@keyframes up { to { opacity: 1; transform: none; } }
.mark.grow i { transform-origin: bottom; transform: scaleY(0); animation: grow 0.7s cubic-bezier(.2,.7,.3,1) forwards; }
.mark.grow i:nth-child(2) { animation-delay: 0.06s; } .mark.grow i:nth-child(3) { animation-delay: 0.12s; }
.mark.grow i:nth-child(4) { animation-delay: 0.18s; } .mark.grow i:nth-child(5) { animation-delay: 0.24s; }
@keyframes grow { to { transform: scaleY(1); } }
body.pre .up, body.pre .mark.grow i { animation-play-state: paused; }
"""

CHIPS = "".join(
    f'<span class="chip"><b style="background: var(--{v})"></b>{k}</span>'
    for k, v in (
        ("MongoDB", "mongo"),
        ("Redis", "redis"),
        ("Cassandra", "cass"),
        ("DynamoDB", "dynamo"),
        ("Neo4j", "neo"),
        ("DuckDB", "duck"),
    )
)

TITLE_HTML = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>title</title><style>{CARD_CSS}
.text {{ position: absolute; left: 92px; top: 0; bottom: 0; width: 760px; display: flex; flex-direction: column; justify-content: center; }}
.kicker {{ display: flex; align-items: center; gap: 14px; font-size: 17px; font-weight: 600; color: var(--muted); letter-spacing: 0.01em; }}
h1 {{ font-family: var(--display); font-weight: 600; font-size: 54px; line-height: 1.08; margin: 26px 0 0; letter-spacing: -0.01em; }}
h1 span {{ color: var(--spring); display: block; font-size: 70px; margin-top: 4px; }}
p.sub {{ font-size: 20px; line-height: 1.55; color: #d3e3dc; margin: 24px 0 30px; max-width: 560px; }}
.shot {{ position: absolute; left: 880px; top: 168px; width: 980px; border-radius: 14px; overflow: hidden; border: 1px solid #2f5a4a;
  box-shadow: 0 50px 110px rgba(0,0,0,0.5), 0 10px 30px rgba(0,0,0,0.3); transform-origin: left center;
  transform: perspective(2200px) rotateY(-14deg) rotateX(3deg); }}
.shot img {{ display: block; width: 100%; }}
.glow {{ position: absolute; left: 820px; top: 120px; width: 760px; height: 640px; border-radius: 50%;
  background: radial-gradient(closest-side, rgba(0,226,107,0.20), rgba(0,226,107,0)); }}
.play {{ display: none; position: absolute; left: 1225px; top: 395px; width: 104px; height: 104px; border-radius: 50%;
  background: rgba(11,44,34,0.92); border: 3px solid var(--spring); box-shadow: 0 12px 40px rgba(0,0,0,0.45); place-items: center; }}
.play i {{ display: block; width: 0; height: 0; margin-left: 8px; border-style: solid; border-width: 20px 0 20px 32px;
  border-color: transparent transparent transparent var(--fg); }}
body.readme .play {{ display: grid; }}
.foot {{ position: absolute; left: 92px; bottom: 46px; font-family: var(--mono); font-size: 15px; color: var(--muted); }}
</style></head><body class="pre"><div class="glow up" style="animation-delay: .3s"></div>
<div class="shot up" style="animation-delay: .35s"><img src="@@SHOT@@" alt=""></div>
<div class="text">
<div class="kicker up"><span class="mark grow"><i></i><i></i><i></i><i></i><i></i></span>An open guide with a local web app</div>
<h1 class="up" style="animation-delay: .15s">NoSQL for data engineers:<span>the lesson studio</span></h1>
<p class="sub up" style="animation-delay: .3s">Lessons with live consoles for MongoDB, Redis, Cassandra, DynamoDB and Neo4j. Run every example and check your answers against real databases on your machine.</p>
<div class="chips up" style="animation-delay: .45s">{CHIPS}</div>
</div>
<div class="foot up" style="animation-delay: .6s">github.com/linusdominic/nosql-for-data-engineers</div>
<div class="play"><i></i></div>
</body></html>"""

OUTRO_HTML = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>outro</title><style>{CARD_CSS}
body {{ background: radial-gradient(1100px 680px at 50% 38%, #10352a 0%, #071a14 60%, #050e0b 100%); }}
.wrap {{ position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }}
h1 {{ font-family: var(--display); font-weight: 600; font-size: 58px; margin: 26px 0 34px; }}
.rows {{ display: grid; grid-template-columns: auto auto; gap: 16px 22px; align-items: center; text-align: left; }}
.k {{ font-size: 15px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--spring); text-align: right; }}
.v {{ font-family: var(--mono); font-size: 23px; padding: 10px 18px; border-radius: 10px; background: rgba(16,58,45,0.75); border: 1px solid var(--line); }}
.v.plain {{ font-family: var(--sans); font-size: 21px; }}
.chips {{ margin-top: 40px; justify-content: center; }}
</style></head><body class="pre"><div class="wrap">
<span class="mark grow"><i></i><i></i><i></i><i></i><i></i></span>
<h1 class="up">Try it on your machine</h1>
<div class="rows">
<div class="k up" style="animation-delay: .15s">Code</div><div class="v up" style="animation-delay: .15s">github.com/linusdominic/nosql-for-data-engineers</div>
<div class="k up" style="animation-delay: .3s">Run</div><div class="v up" style="animation-delay: .3s">make setup &amp;&amp; make up-capstone up-05 &amp;&amp; make studio</div>
<div class="k up" style="animation-delay: .45s">No install</div><div class="v up" style="animation-delay: .45s">linusdominic.github.io/nosql-for-data-engineers/explorer</div>
</div>
<div class="chips up" style="animation-delay: .6s">{CHIPS}</div>
</div></body></html>"""

TERMINAL_HTML = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>install</title><style>{CARD_CSS}
.steps {{ position: absolute; top: 46px; left: 0; right: 0; display: flex; justify-content: center; gap: 12px; }}
.step {{ display: inline-flex; align-items: center; gap: 10px; padding: 8px 16px 8px 9px; border-radius: 999px; border: 1px solid var(--line);
  background: rgba(16,58,45,0.55); color: var(--muted); font-size: 16px; font-weight: 600; transition: all .35s; }}
.step .n {{ width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; font-size: 13px; border: 1.5px solid var(--line); transition: all .35s; }}
.step.on {{ color: var(--fg); border-color: var(--spring); background: rgba(0,226,107,0.10); }}
.step.on .n {{ background: var(--spring); color: #04150d; border-color: var(--spring); }}
.step.done .n {{ background: #1d5c45; color: var(--fg); border-color: #1d5c45; }}
.win {{ position: absolute; left: 50%; top: 112px; transform: translateX(-50%); width: 1220px; height: 600px; border-radius: 12px; overflow: hidden;
  background: #08110e; border: 1px solid #23453a; box-shadow: 0 40px 90px rgba(0,0,0,0.5), 0 6px 18px rgba(0,0,0,0.3); }}
.bar {{ height: 38px; display: flex; align-items: center; gap: 8px; padding: 0 14px; background: #0f1f19; border-bottom: 1px solid #1d3a30; }}
.bar i {{ width: 12px; height: 12px; border-radius: 50%; display: block; }}
.bar .t {{ flex: 1; text-align: center; color: #8fa099; font-size: 13.5px; font-weight: 600; margin-right: 60px; }}
.screen {{ position: absolute; top: 38px; left: 0; right: 0; bottom: 0; overflow: hidden; padding: 16px 24px; }}
.lines {{ font-family: var(--mono); font-size: 17px; line-height: 27px; color: #c9d6d0; white-space: pre; transition: transform .35s cubic-bezier(.2,.7,.3,1); }}
.l.cmd {{ color: #f1f7f4; }}
.p {{ color: var(--spring); font-weight: 600; }} .cwd {{ color: #7fd8e0; }}
.dim {{ color: #7d9089; }}
.ok {{ color: #6fdc9c; }}
.url {{ color: #7cc4ff; text-decoration: underline; text-underline-offset: 3px; border-radius: 4px; transition: background .3s; }}
.url.hi {{ background: rgba(124,196,255,0.18); }}
.caret {{ display: inline-block; width: 10px; height: 20px; background: #f1f7f4; vertical-align: -4px; margin-left: 1px; animation: blink 1s steps(1) infinite; }}
@keyframes blink {{ 50% {{ opacity: 0; }} }}
</style></head><body>
<div class="steps">@@STEPS@@</div>
<div class="win"><div class="bar"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i><span class="t">Terminal</span></div>
<div class="screen" id="screen"><div class="lines" id="lines"></div></div></div>
<script>
const lines = document.getElementById("lines"), screen = document.getElementById("screen");
let rnd = 7;
function rand() {{ rnd = (rnd * 16807) % 2147483647; return rnd / 2147483647; }}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function esc(s) {{ return s.replace(/[&<>]/g, (c) => ({{"&": "&amp;", "<": "&lt;", ">": "&gt;"}})[c]); }}
function follow() {{
  const over = lines.scrollHeight - (screen.clientHeight - 32);
  lines.style.transform = over > 0 ? "translateY(" + (-over) + "px)" : "none";
}}
let current = null;
function prompt(cwd) {{
  const d = document.createElement("div"); d.className = "l cmd";
  d.innerHTML = '<span class="cwd">' + esc(cwd) + '</span> <span class="p">$</span> <span class="typed"></span><span class="caret"></span>';
  lines.appendChild(d); current = d; follow();
}}
window.term = {{
  async type(cwd, text) {{
    prompt(cwd);
    const t = current.querySelector(".typed");
    await sleep(380);
    for (const ch of text) {{
      t.textContent += ch;
      let d = 38 + rand() * 46;
      if (ch === " ") d += 45; if ("/.-".includes(ch)) d += 20;
      await sleep(d);
    }}
    await sleep(260);
    current.querySelector(".caret").remove();
  }},
  async out(list, url) {{
    for (const s of list) {{
      const d = document.createElement("div"); d.className = "l";
      let h = esc(s);
      if (s.startsWith("Setup done") || / Healthy$/.test(s)) h = '<span class="ok">' + h + '</span>';
      else if (/^(uv |docker compose )/.test(s) || s.trim() === "...") h = '<span class="dim">' + h + '</span>';
      h = h.replace("@@URL@@", '<span class="url" id="url">' + esc(url) + '</span>');
      d.innerHTML = h || " ";
      lines.appendChild(d); follow();
      await sleep(s.startsWith(" +") ? 40 : s.startsWith("remote") || s.startsWith("Receiving") ? 170 : 110);
    }}
  }},
  step(i) {{
    document.querySelectorAll(".step").forEach((el, j) => {{ el.className = "step" + (j < i ? " done" : j === i ? " on" : ""); }});
  }},
  urlBox() {{ const u = document.getElementById("url"); const r = u.getBoundingClientRect(); return {{ x: r.left, y: r.top, w: r.width, h: r.height }}; }},
  highlight() {{ document.getElementById("url").classList.add("hi"); }},
}};
</script></body></html>"""


# ---------------------------------------------------------------------------------
# The studio, started for the recording only.
def serve(port: int, progress_path: Path) -> None:
    """The studio as `make studio` runs it, but with progress in progress_path."""
    import uvicorn

    from nosqlde.studio import server
    from nosqlde.studio.progress import Progress

    token = os.environ[TOKEN_ENV]
    app = server.create_app(token, port, progress=Progress(progress_path))
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    finally:
        app.fastapi.state.consoles.close()


class Studio:
    def __init__(self, port: int, work: Path) -> None:
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self.progress = work / "progress.json"
        self.progress.unlink(missing_ok=True)
        self.proc: subprocess.Popen[bytes] | None = None
        self.base = f"http://127.0.0.1:{port}"

    def start(self) -> None:
        import httpx

        with contextlib.suppress(httpx.HTTPError):
            httpx.get(self.base + "/", timeout=1)
            raise SystemExit(f"Port {self.port} is in use; pass --port.")
        env = {**os.environ, TOKEN_ENV: self.token}
        self.proc = subprocess.Popen(
            [sys.executable, __file__, "serve", "--port", str(self.port), "--progress", str(self.progress)],
            cwd=ROOT,
            env=env,
        )
        for _ in range(120):
            try:
                if httpx.get(self.base + "/api/status", headers=self.headers, timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise SystemExit("The studio did not start.")

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Studio-Token": self.token}

    def api(self, path: str, body: dict[str, Any] | None = None) -> Any:
        import httpx

        if body is None:
            r = httpx.get(self.base + path, headers=self.headers, timeout=120)
        else:
            r = httpx.post(self.base + path, headers=self.headers, json=body, timeout=300)
        r.raise_for_status()
        return r.json()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def prepare_and_seed(studio: Studio) -> None:
    """Load the chapters' data and pass a few exercises with their reference solutions."""
    from nosqlde.studio.registry import LESSONS

    services = studio.api("/api/status")["services"]
    down = [s["label"] for s in services if not s["up"]]
    if down:
        raise SystemExit(f"Start every database first (make up-capstone up-05); down: {', '.join(down)}")
    for lesson_id in ("ch02", "ch03", "ch04", "ch05", "ch06"):
        res = studio.api(f"/api/prepare/{lesson_id}", {})
        print(f"  prepared {lesson_id} in {res['seconds']} s")
    quiz = LESSONS["ch01"].quiz
    studio.api("/api/quiz/ch01", {"answers": {q.id: q.answer for q in quiz}})
    wanted: list[str] = []
    for item in SEED_PASSES:
        if item.endswith("."):
            lesson = LESSONS[item[:-1]]
            wanted += [x.id for x in lesson.exercises[: SEED_COUNTS[item]]]
        else:
            wanted.append(item)
    for lesson in LESSONS.values():
        for x in lesson.exercises:
            if x.id in wanted:
                res = studio.api("/api/check", {"exercise_id": x.id, "answer": x.solution})
                print(f"  {x.id}: {'PASS' if res['ok'] else 'FAIL'}")


# ---------------------------------------------------------------------------------
# Capture: CDP screencast frames to constant-rate clips.
class Clip:
    """One clip: frames written to ffmpeg at a constant FPS, by their timestamps."""

    def __init__(self, path: Path, first: bytes, t0: float) -> None:
        self.path = path
        self.t0 = t0
        self.current = first
        self.count = 0
        self.q: queue.Queue[bytes | None] = queue.Queue()
        self.proc = subprocess.Popen(
            [
                "ffmpeg", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS),
                "-c:v", "mjpeg", "-i", "-",
                "-vf", f"scale={OUT_W}:{OUT_H}:flags=lanczos:{TO_VIDEO},format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "10", "-r", str(FPS), *COLOR, str(path),
            ],
            stdin=subprocess.PIPE,
        )  # fmt: skip
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def _write(self) -> None:
        assert self.proc.stdin is not None
        while True:
            item = self.q.get()
            if item is None:
                break
            self.proc.stdin.write(item)
        self.proc.stdin.close()

    def advance(self, until: float) -> None:
        target = math.floor((until - self.t0) * FPS)
        while self.count < target:
            self.q.put(self.current)
            self.count += 1

    def frame(self, ts: float, data: bytes) -> None:
        self.advance(ts)
        self.current = data

    def close(self, until: float) -> float:
        self.advance(until)
        if self.count == 0:
            self.q.put(self.current)
            self.count = 1
        self.q.put(None)
        self.thread.join()
        self.proc.wait()
        return self.count / FPS


class Recorder:
    def __init__(self, work: Path) -> None:
        self.dir = work / "clips"
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        self.latest: bytes | None = None
        self.clip: Clip | None = None
        self.clips: dict[str, tuple[Path, float]] = {}
        self.marks: dict[str, float] = {}
        self.cdp: Any = None
        self.acks: set[asyncio.Future[Any]] = set()

    async def attach(self, page: Any) -> None:
        self.cdp = await page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._on_frame)
        await self.cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 95, "maxWidth": OUT_W, "maxHeight": OUT_H, "everyNthFrame": 1},
        )
        for _ in range(100):
            if self.latest is not None:
                return
            await asyncio.sleep(0.05)

    def _on_frame(self, params: dict[str, Any]) -> None:
        data = base64.b64decode(params["data"])
        ts = float(params["metadata"].get("timestamp") or time.time())
        self.latest = data
        if self.clip is not None:
            self.clip.frame(ts, data)
        task = asyncio.ensure_future(
            self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        )
        self.acks.add(task)
        task.add_done_callback(self.acks.discard)

    async def begin(self, name: str) -> None:
        await asyncio.sleep(0.25)  # let pending frames land first
        assert self.latest is not None
        self.clip = Clip(self.dir / f"{len(self.clips):02d}-{name}.mp4", self.latest, time.time())
        self.name = name

    def mark(self, label: str) -> None:
        """Remember a moment (seconds into the current clip), e.g. where the GIF starts."""
        assert self.clip is not None
        self.marks[label] = time.time() - self.clip.t0
        self.marks[label + ":clip"] = float(len(self.clips))

    async def end(self) -> None:
        assert self.clip is not None
        await asyncio.sleep(0.1)
        clip, self.clip = self.clip, None
        seconds = await asyncio.to_thread(clip.close, time.time())
        self.clips[self.name] = (clip.path, seconds)
        print(f"  clip {clip.path.name}: {seconds:.1f} s")


# ---------------------------------------------------------------------------------
# Driving the page.
class Director:
    def __init__(self, page: Any, rec: Recorder) -> None:
        self.page = page
        self.rec = rec
        self.rnd = random.Random(20261119)

    async def js(self, script: str, arg: Any = None) -> Any:
        return await self.page.evaluate(script, arg)

    async def wait(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def caption(self, text: str, kicker: str = "", where: str = "center") -> None:
        await self.js("([t, k, w]) => window.__demo.caption(t, k, w)", [text, kicker, where])

    async def uncaption(self) -> None:
        await self.js("() => window.__demo.uncaption()")

    async def cursor_to(self, x: float, y: float, ms: int = 0) -> None:
        await self.js("([x, y, ms]) => window.__demo.move(x, y, ms)", [x, y, ms])
        await self.page.mouse.move(x, y)

    async def center_of(self, target: Any, dx: float = 0.5, dy: float = 0.5) -> tuple[float, float]:
        await target.wait_for(state="visible", timeout=30_000)
        box = await target.bounding_box()
        assert box is not None
        return box["x"] + box["width"] * dx, box["y"] + box["height"] * dy

    async def hover(self, target: Any, dx: float = 0.5, dy: float = 0.5) -> None:
        x, y = await self.center_of(target, dx, dy)
        await self.cursor_to(x, y)

    async def click(self, target: Any, dx: float = 0.5, dy: float = 0.5, settle: float = 0.15) -> None:
        x, y = await self.center_of(target, dx, dy)
        await self.cursor_to(x, y)
        await asyncio.sleep(0.12)
        await asyncio.gather(self.js("() => window.__demo.click()"), self.page.mouse.click(x, y))
        await asyncio.sleep(settle)

    async def scroll_to(self, target: Any, offset: float = 24, ms: int = 0) -> None:
        handle = await target.element_handle(timeout=30_000)
        await handle.evaluate("(el, [o, ms]) => window.__demo.scrollTo(el, o, ms)", [offset, ms])

    async def type(self, text: str, cps: float = 13.0) -> None:
        for ch in text:
            await self.page.keyboard.type(ch)
            delay = 1 / cps * (0.55 + self.rnd.random() * 0.9)
            if ch in " ,":
                delay += 0.06
            await asyncio.sleep(delay)

    async def run_done(self) -> None:
        await asyncio.sleep(0.15)
        await self.page.wait_for_function(
            "() => !document.getElementById('run-btn').disabled", timeout=60_000
        )

    async def goto(self, hash_: str) -> None:
        await self.js("(h) => { location.hash = h; }", hash_)
        await asyncio.sleep(1.2)


async def record_studio(d: Director, studio: Studio, work: Path) -> None:
    page, rec = d.page, d.rec
    L = page.locator

    await page.goto(f"{studio.base}/?token={studio.token}#/")
    await page.wait_for_function(
        "() => document.querySelectorAll('#statusbar .svc.up').length === 6", timeout=30_000
    )
    await page.wait_for_timeout(800)
    await d.js("() => { window.__demo.jump(820, 560); window.__demo.show(); }")

    # Home: the status bar, the chapters, the rings.
    await rec.begin("home")
    await d.wait(0.6)
    await d.caption("Every database is up: the status bar at the bottom shows each one", "The lesson studio")
    await d.hover(L("#statusbar .svc").nth(0))
    await d.hover(L("#statusbar .svc").nth(5), 0.3)
    await d.wait(1.0)
    await d.caption(
        "One tab per chapter at the top, with a ring for your progress", "The lesson studio", "left"
    )
    await d.hover(L("#chapter-nav a").nth(0))
    await d.hover(L("#chapter-nav a").nth(4))
    await d.wait(0.5)
    await d.scroll_to(L("#lesson-inner .cards"), 110, 1100)
    await d.wait(1.6)
    await d.uncaption()
    await d.click(L("#chapter-nav a[href='#/ch02']"))
    await page.wait_for_selector("#prepare-btn")
    await d.wait(0.9)

    # Chapter 2: Prepare data.
    await d.caption(
        "Prepare data loads the chapter's data with the lab's own code", "Chapter 2 · MongoDB", "right"
    )
    await d.click(L("#prepare-btn"))
    await page.wait_for_selector("#prepare-out .panel", timeout=60_000)
    await d.hover(L("#prepare-out .panel"), 0.92, 0.18)
    await d.wait(2.4)

    # Run this: a document as a JSON tree.
    await d.click(L("#steps button").nth(1))
    await d.wait(0.8)
    await d.caption(
        "Run this sends an example to a console on the real database", "Chapter 2 · MongoDB", "left"
    )
    await d.click(L("button[aria-label^='Run this: Embedded']"))
    await d.run_done()
    await d.hover(L("#results .block").first, 0.3, 0.45)
    await d.wait(2.4)
    await d.uncaption()
    await rec.end()

    # An exercise: FAIL, a hint, PASS.
    await d.goto("#/ch02/indexes")
    card = L("#ex-ch02\\.ixscan")
    await d.scroll_to(card, 18, 300)
    await d.wait(0.4)
    await rec.begin("exercise")
    await d.wait(0.5)
    await d.caption("Exercise 2.3: make this query use an index", "Chapter 2 · MongoDB", "right")
    await d.wait(1.0)
    await d.click(card.get_by_role("button", name="Work on this"))
    await d.js(
        "() => { const e = document.getElementById('editor'); e.setSelectionRange(0, 0); e.scrollLeft = 0; }"
    )
    await d.wait(1.0)
    await d.caption(
        "Work on this loads the starter into the console. Type an answer", "Exercise 2.3", "right"
    )
    editor = L("#editor")
    await d.click(editor, 0.03, 0.12)
    first = (await editor.input_value()).split("\n")[0]
    await d.js(
        "(n) => { const e = document.getElementById('editor'); e.focus(); e.setSelectionRange(0, n); e.scrollLeft = 0; }",
        len(first),
    )
    await d.wait(0.7)
    await d.type("db.applications.createIndex({submitted_at: 1, status: 1})")
    await d.wait(0.6)
    await d.click(L("#working-check"))
    await page.wait_for_selector("#verdict-ch02\\.ixscan .verdict", timeout=60_000)
    await d.wait(0.3)
    await d.scroll_to(card, 18, 500)
    await d.caption("FAIL: the check shows what it expected and what it got", "Exercise 2.3", "right")
    await d.hover(L("#verdict-ch02\\.ixscan .verdict-grid"), 0.96, 0.62)
    await d.wait(3.2)
    await d.caption("Hints open one at a time", "Exercise 2.3", "right")
    hint = card.locator(".actions button").nth(2)
    await d.click(hint)
    await d.wait(1.3)
    await d.click(hint)
    await d.wait(2.0)
    rec.mark("gif-start")
    await d.caption("Fix the answer: the equality field first, then the sort field", "Exercise 2.3", "right")
    text = await editor.input_value()
    start = text.index("submitted_at: 1, status: 1")
    await d.click(editor, 0.2, 0.12)
    await d.js(
        "([a, b]) => { const e = document.getElementById('editor'); e.focus(); e.setSelectionRange(a, b); e.scrollLeft = 0; }",
        [start, start + len("submitted_at: 1, status: 1")],
    )
    await d.wait(0.6)
    await d.type("status: 1, submitted_at: 1")
    await d.wait(0.5)
    await d.click(L("#working-check"))
    await page.wait_for_selector("#verdict-ch02\\.ixscan .verdict.pass", timeout=60_000)
    await d.wait(0.2)
    await d.caption("PASS, and your progress is saved", "Exercise 2.3", "right")
    await d.hover(L("#state-ch02\\.ixscan"), 0.3, 1.25)
    await d.wait(1.6)
    await d.wait(1.0)
    rec.mark("gif-end")
    await d.hover(L("#chapter-nav a[href='#/ch02'] .ring"))
    await d.wait(1.4)
    await d.uncaption()
    await rec.end()
    # The still for the title card: exercise 2.3 passed, without the overlay.
    await d.js("() => window.__demo.hide()")
    await d.scroll_to(card, 18, 300)
    await page.screenshot(path=str(work / "shot-pass.png"))
    await d.js("() => window.__demo.show()")

    # The reader beside the console: Open in Neo4j.
    await d.goto("#/ch06/patterns")
    await d.js("() => window.__demo.jump(600, 600)")
    await rec.begin("reader")
    await d.wait(0.5)
    await d.caption("Read this section opens the guide beside the console", "Chapter 6 · Neo4j", "right")
    await d.click(L("#step .guide-link"))
    await page.wait_for_selector("#reader-body .codeblock [data-console='cypher']")
    await d.wait(1.4)
    block = L("#reader-body .codeblock.acc-cypher").first
    await d.scroll_to(block, 90, 900)
    await d.wait(0.6)
    await d.caption("Open in Neo4j puts the query in the console", "Chapter 6 · Neo4j", "left")
    await d.click(block.locator("[data-console='cypher']"))
    await d.wait(1.0)
    await d.click(L("#run-btn"))
    await d.run_done()
    await d.caption(
        "The same answer as the guide: 11 pairs of applications share a phone", "Chapter 6 · Neo4j", "left"
    )
    await d.hover(L("#results table").first, 0.5, 0.4)
    await d.wait(2.6)
    await d.uncaption()
    await rec.end()

    # A quick tour.
    async def tour(name: str, hash_: str, kicker: str, text: str, button: str, then: Any = None) -> None:
        await d.goto(hash_)
        await d.js("() => window.__demo.jump(560, 640)")
        await rec.begin(name)
        await d.wait(0.4)
        await d.caption(text, kicker, "left")
        await d.wait(0.8)
        await d.click(L(f"button[aria-label='Run this: {button}']"))
        await d.run_done()
        if then is not None:
            await then()
        await d.wait(3.2)
        await d.uncaption()
        await rec.end()

    await tour(
        "redis",
        "#/ch03/streams",
        "Chapter 3 · Redis",
        "Redis streams and consumer groups, in redis-cli syntax",
        "The first entries",
    )

    async def show_trace() -> None:
        await d.wait(0.8)
        notes = L("#results .block").nth(1).locator(".notes")
        await d.scroll_to(notes, 260, 1000)
        await d.hover(notes, 0.3, 0.3)

    await tour(
        "cassandra",
        "#/ch04/allow-filtering",
        "Chapter 4 · Cassandra",
        "CQL with TRACING ON: the trace shows what one query read",
        "One partition, traced",
        show_trace,
    )

    async def show_capacity() -> None:
        await d.hover(L("#results").get_by_text("ConsumedCapacity").first, 0.12, 1.7)

    await tour(
        "dynamodb",
        "#/ch05/access-patterns",
        "Chapter 5 · DynamoDB",
        "DynamoDB Local in JSON mode reports the capacity each read consumed",
        "AP1 as GetItem (JSON mode)",
        show_capacity,
    )

    async def show_hits() -> None:
        await d.hover(L("#results").get_by_text("total db hits").first, 0.12, 1.7)

    await tour(
        "neo4j",
        "#/ch06/profile",
        "Chapter 6 · Neo4j",
        "PROFILE shows the plan, operator by operator, with its db hits",
        "A label scan",
        show_hits,
    )

    # Chapter 7: the capstone, streamed stage by stage.
    await d.goto("#/ch07")
    await d.js("() => window.__demo.jump(700, 640)")
    await rec.begin("capstone")
    await d.wait(0.4)
    await d.caption(
        "The capstone runs from the browser and streams each stage", "Chapter 7 · Capstone", "right"
    )
    await d.click(L(".job .btn.primary"))
    await page.wait_for_function(
        "() => /finished|failed|stopped/.test(document.querySelector('.job .small.muted').textContent)",
        timeout=180_000,
    )
    await d.hover(L(".job .stages li").last, 0.35)
    await d.wait(1.2)
    await d.scroll_to(L(".job .log"), 130, 1000)
    await d.hover(L(".job .log"), 0.8, 0.92)
    await d.wait(2.6)
    await d.uncaption()
    await rec.end()

    # Chapter 8 in the reader, then search, the theme and the rings.
    await d.goto("#/read/08")
    await d.js("() => window.__demo.jump(900, 600)")
    await rec.begin("finish")
    await d.wait(0.4)
    await d.caption(
        "Read shows every chapter of the guide, with its diagrams", "Chapter 8 · Choosing a database", "high"
    )
    await d.scroll_to(L("#reader-body figure.diagram").first, 70, 1400)
    await d.hover(L("#reader-body figure.diagram").first, 0.5, 0.35)
    await d.wait(2.2)
    await d.js("() => document.activeElement && document.activeElement.blur()")
    await d.caption("Press / to search every chapter", "Search", "left")
    await d.wait(0.6)
    await page.keyboard.press("/")
    await d.wait(0.5)
    await d.type("ALLOW FILTERING", cps=11)
    await page.wait_for_selector("#search-results li a")
    await d.hover(L("#search-results li a").first, 0.3)
    await d.wait(1.8)
    await page.keyboard.press("Enter")
    await d.wait(1.6)
    await d.caption("Light or dark, as you like", "Theme")
    await d.click(L("#theme-toggle"))
    await d.wait(1.6)
    await d.uncaption()
    await d.click(L("a.brand"))
    await d.wait(1.0)
    await d.caption("Your progress is saved, chapter by chapter", "The lesson studio", "right")
    await d.scroll_to(L("#lesson-inner .cards"), 110, 1100)
    await d.hover(L("#chapter-nav a[href='#/ch01'] .ring"))
    await d.hover(L("#chapter-nav a[href='#/ch04'] .ring"))
    await d.wait(2.4)
    await d.uncaption()
    await d.js("() => window.__demo.hide()")
    await d.wait(0.4)
    await rec.end()


async def record_cards(d: Director, work: Path) -> None:
    page, rec = d.page, d.rec
    shot = work / "shot-pass.png"
    title = work / "title.html"
    title.write_text(TITLE_HTML.replace("@@SHOT@@", shot.as_uri()))
    steps = "".join(
        f'<span class="step"><span class="n">{i + 1}</span>{html.escape(s)}</span>'
        for i, s in enumerate(INSTALL_STEPS)
    )
    terminal = work / "terminal.html"
    terminal.write_text(TERMINAL_HTML.replace("@@STEPS@@", steps))
    outro = work / "outro.html"
    outro.write_text(OUTRO_HTML)

    # Title: the elements rise in, then the still for the poster.
    await page.goto(title.as_uri())
    await page.wait_for_load_state("load")
    await d.js("() => window.__demo.hide()")
    await rec.begin("title")
    await d.wait(0.3)
    await d.js("() => document.body.classList.remove('pre')")
    await d.wait(4.4)
    await page.screenshot(path=str(work / "poster.png"))
    await rec.end()
    # The README's copy of the still carries a play button: it links to the video.
    await d.js("() => document.body.classList.add('readme')")
    await page.screenshot(path=str(work / "poster-readme.png"))

    # Install.
    await page.goto(terminal.as_uri())
    await d.js("() => { window.__demo.hide(); window.term.step(0); }")
    await rec.begin("install")
    await d.wait(0.4)
    for item in INSTALL:
        await d.js("(i) => window.term.step(i)", item["step"])
        if item.get("caption"):
            await d.caption(item["caption"], f"Install · step {item['step'] + 1} of 4")
        await d.js("([c, t]) => window.term.type(c, t)", [item["cwd"], item["cmd"]])
        if item["cmd"] == "make studio":
            await d.wait(1.4)
        await d.js("([o, u]) => window.term.out(o, u)", [item["out"], STUDIO_URL_SHOWN])
        await d.wait(0.9 if item["out"] else 0.2)
    box = await d.js("() => window.term.urlBox()")
    await d.js("() => window.__demo.jump(1000, 700)")
    await d.js("() => window.__demo.show()")
    await d.cursor_to(box["x"] + box["w"] * 0.88, box["y"] + box["h"] * 0.75)
    await d.js("() => { window.term.highlight(); return window.__demo.click(); }")
    await d.caption("Open the address it prints, with its token, in your browser", "Install · step 4 of 4")
    await d.wait(2.2)
    await rec.end()

    # Outro.
    await page.goto(outro.as_uri())
    await page.wait_for_load_state("load")
    await d.js("() => window.__demo.hide()")
    await rec.begin("outro")
    await d.wait(0.3)
    await d.js("() => document.body.classList.remove('pre')")
    await d.wait(5.4)
    await rec.end()


async def record(studio: Studio, work: Path, headed: bool) -> Recorder:
    from playwright.async_api import async_playwright

    rec = Recorder(work)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(channel="chrome", headless=not headed)
        ctx = await browser.new_context(
            viewport={"width": VIEW_W, "height": VIEW_H}, device_scale_factor=SCALE, color_scheme="light"
        )
        await ctx.add_init_script(OVERLAY_JS)
        page = await ctx.new_page()
        await page.goto("about:blank")
        await rec.attach(page)
        d = Director(page, rec)
        try:
            await record_studio(d, studio, work)
            await record_cards(d, work)
        except Exception:
            await page.screenshot(path=str(work / "error.png"))
            print(f"  failed; the page as it was: {work / 'error.png'}")
            raise
        await browser.close()
    return rec


# ---------------------------------------------------------------------------------
# Assembly.
ORDER = (
    "title",
    "install",
    "home",
    "exercise",
    "reader",
    "redis",
    "cassandra",
    "dynamodb",
    "neo4j",
    "capstone",
    "finish",
    "outro",
)
XFADE = {"install": 0.7, "home": 0.7, "outro": 0.8}  # into this clip; others 0.45 s


def run(cmd: list[str]) -> str:
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out.stdout + out.stderr


def probe_seconds(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.strip())


def assemble(rec: Recorder, work: Path, out: Path, music: Path | None) -> float:
    clips = [rec.clips[name] for name in ORDER]
    inputs: list[str] = []
    for path, _ in clips:
        inputs += ["-i", str(path)]
    parts: list[str] = []
    label = "[0:v]"
    total = probe_seconds(clips[0][0])
    for i in range(1, len(clips)):
        fade = XFADE.get(ORDER[i], 0.45)
        offset = total - fade
        nxt = f"[v{i}]"
        parts.append(f"{label}[{i}:v]xfade=transition=fade:duration={fade}:offset={offset:.3f}{nxt}")
        label = nxt
        total = offset + probe_seconds(clips[i][0])
    parts.append(f"{label}format=yuv420p[v]")
    audio: list[str] = []
    if music is not None:
        inputs += ["-i", str(music_bed(music, total, work))]
        audio = ["-map", f"{len(clips)}:a", "-c:a", "aac", "-b:a", "160k"]
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(parts),
        "-map", "[v]", *audio, "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-tune", "stillimage",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS), *COLOR, "-movflags", "+faststart",
        "-t", f"{total:.3f}", str(out),
    ]  # fmt: skip
    run(cmd)
    return total


def music_bed(music: Path, seconds: float, work: Path) -> Path:
    """The music, looped or cut to the video's length, faded in and out, then turned to
    TARGET_LUFS integrated loudness (measured with ebur128, applied as a plain gain)."""
    bed = work / "music-bed.wav"
    run(["ffmpeg", "-loglevel", "error", "-y", "-stream_loop", "-1", "-i", str(music), "-t", f"{seconds:.3f}",
         "-af", f"afade=t=in:d=2,afade=t=out:st={seconds - 3.5:.3f}:d=3.5", "-ar", "48000", "-ac", "2",
         str(bed)])  # fmt: skip
    stats = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(bed), "-af", "ebur128", "-f", "null", "-"])
    integrated = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", stats)[-1])
    out = work / "music-bed-normalised.wav"
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(bed), "-af", f"volume={TARGET_LUFS - integrated:.2f}dB",
         str(out)])  # fmt: skip
    print(f"  music: {music.name}, {integrated:.1f} LUFS -> {TARGET_LUFS:.0f} LUFS")
    return out


def stills(work: Path, poster_png: Path, poster_jpg: Path) -> None:
    poster_png.parent.mkdir(parents=True, exist_ok=True)
    poster_jpg.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(work / "poster.png"),
         "-vf", f"scale={OUT_W}:{OUT_H}:flags=lanczos", str(poster_png)])  # fmt: skip
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(work / "poster-readme.png"),
         "-vf", "scale=1280:720:flags=lanczos", "-q:v", "3", str(poster_jpg)])  # fmt: skip


def gif(rec: Recorder, out: Path) -> None:
    """The exercise clip from the fix to PASS, cropped to the card and the editor."""
    path, _ = rec.clips["exercise"]
    start, end = rec.marks["gif-start"], rec.marks["gif-end"]
    crop = "crop=1404:790:0:70"  # the card and the editor, above the captions
    vf = (
        f"{crop},fps=12,scale=960:-1:flags=lanczos,split[a][b];"
        "[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}", "-i", str(path),
         "-filter_complex", vf, "-loop", "0", str(out)])  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command")
    srv = sub.add_parser("serve", help="(internal) the studio for the recording")
    srv.add_argument("--port", type=int, required=True)
    srv.add_argument("--progress", type=Path, required=True)
    parser.add_argument(
        "--port", type=int, default=8792, help="port for the recording's own studio (default 8792)"
    )
    parser.add_argument(
        "--work",
        type=Path,
        default=Path(os.environ.get("TMPDIR", "/tmp")) / "nosqlde-demo",
        help="scratch folder",
    )
    parser.add_argument(
        "--music", type=Path, default=DEFAULT_MUSIC, help="music bed (CC0); --music none for silence"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "media" / "studio-demo.mp4")
    parser.add_argument("--headed", action="store_true", help="show the browser while recording")
    args = parser.parse_args(argv)
    if args.command == "serve":
        serve(args.port, args.progress)
        return 0

    music: Path | None = None if str(args.music) == "none" else args.music
    if music is not None and not music.is_file():
        raise SystemExit(f"No music at {music}; pass --music <file> or --music none.")
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is needed (brew install ffmpeg).")
    work: Path = args.work
    work.mkdir(parents=True, exist_ok=True)
    studio = Studio(args.port, work)
    print(f"Starting a studio for the recording on 127.0.0.1:{args.port} (progress in {studio.progress})")
    studio.start()
    try:
        print("Preparing data and passing a few exercises")
        prepare_and_seed(studio)
        print("Recording")
        rec = asyncio.run(record(studio, work, args.headed))
    finally:
        studio.stop()
    (work / "marks.json").write_text(json.dumps(rec.marks, indent=2))
    print("Assembling")
    total = assemble(rec, work, args.out, music)
    stills(
        work,
        ROOT / "docs" / "media" / "studio-demo-poster.png",
        ROOT / "docs" / "img" / "studio-demo-poster.jpg",
    )
    gif(rec, ROOT / "docs" / "img" / "studio-demo.gif")
    size = args.out.stat().st_size / 1e6
    print(
        f"Wrote {args.out.relative_to(ROOT)}: {total:.1f} s, {size:.1f} MB; the poster and the GIF in docs/"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
