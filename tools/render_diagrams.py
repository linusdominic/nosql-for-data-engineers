"""Pre-render the guide's mermaid diagrams to SVG for the lesson studio's reader.

    make diagrams        (needs Google Chrome or Chromium, nothing else)

Runs mermaid 12.3.0 (MIT) in headless Chrome from a local file: once with a light and once with
a dark theme that match the studio. It writes
src/nosqlde/studio/static/diagrams/<key>-light.svg and <key>-dark.svg, where <key> is the
diagram source's content hash (nosqlde.studio.reader.diagram_key), and removes SVGs no
diagram uses any more. The reader shows them as images, so the page never runs a diagram
library and the studio's Content-Security-Policy stays strict. A unit test fails when a
diagram in the guide has no SVGs, so an edited diagram is not forgotten.

Mermaid is not kept in this repository. On first use the tool downloads the pinned npm
tarball, checks dist/mermaid.min.js against the sha256 below and caches it in
tools/.cache/ (gitignored); later runs work offline.

Set CHROME to the browser's path if it is not in a usual place.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nosqlde.studio.reader import DIAGRAMS, diagram_key, mermaid_blocks  # noqa: E402

MERMAID_VERSION = "12.3.0"
MERMAID = ROOT / "tools" / ".cache" / f"mermaid-{MERMAID_VERSION}" / "mermaid.min.js"
MERMAID_TARBALL = f"https://registry.npmjs.org/mermaid/-/mermaid-{MERMAID_VERSION}.tgz"
# sha256 of dist/mermaid.min.js in https://registry.npmjs.org/mermaid/-/mermaid-12.3.0.tgz
# (the tarball's npm integrity is sha512-4113TdXeLAsMruJ79OpFL5O8+LTFXhQqZ260rF3tgUmiNAtRm4U...)
MERMAID_SHA256 = "336df803d87a38b70a01e736e666c8f7601d2ce42f5e47c8fafe5d721074b9a3"

FONT = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
# The studio's colour tokens (src/nosqlde/studio/static/styles.css).
THEMES = {
    "light": {
        "darkMode": False,
        "background": "#fcfcfb",
        "primaryColor": "#fcfcfb",
        "primaryTextColor": "#0b0b0b",
        "primaryBorderColor": "#a9a8a1",
        "secondaryColor": "#f0efeb",
        "tertiaryColor": "#f4f4f1",
        "mainBkg": "#fcfcfb",
        "nodeBorder": "#a9a8a1",
        "clusterBkg": "#f4f4f1",
        "clusterBorder": "#c6c5be",
        "titleColor": "#43423f",
        "lineColor": "#64635e",
        "textColor": "#0b0b0b",
        "edgeLabelBackground": "#f0efeb",
        "fontFamily": FONT,
        "fontSize": "15px",
    },
    "dark": {
        "darkMode": True,
        "background": "#1a1a19",
        "primaryColor": "#222220",
        "primaryTextColor": "#f0efec",
        "primaryBorderColor": "#5a5953",
        "secondaryColor": "#2b2b29",
        "tertiaryColor": "#1a1a19",
        "mainBkg": "#222220",
        "nodeBorder": "#5a5953",
        "clusterBkg": "#1a1a19",
        "clusterBorder": "#45443f",
        "titleColor": "#c9c8bf",
        "lineColor": "#9d9c93",
        "textColor": "#f0efec",
        "edgeLabelBackground": "#2b2b29",
        "fontFamily": FONT,
        "fontSize": "15px",
    },
}

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>diagrams</title></head>
<body>
<script type="application/json" id="sources">{sources}</script>
<script type="application/json" id="themes">{themes}</script>
<script src="{mermaid}"></script>
<script>
(async function () {{
  var sources = JSON.parse(document.getElementById("sources").textContent);
  var themes = JSON.parse(document.getElementById("themes").textContent);
  for (var theme of Object.keys(themes)) {{
    mermaid.initialize({{
      startOnLoad: false, theme: "base", themeVariables: themes[theme], securityLevel: "strict",
      htmlLabels: false, markdownAutoWrap: false, fontFamily: themes[theme].fontFamily,
      flowchart: {{ htmlLabels: false, curve: "basis", padding: 14, nodeSpacing: 40, rankSpacing: 50, wrappingWidth: 400 }}
    }});
    for (var i = 0; i < sources.length; i++) {{
      var out = await mermaid.render("d" + i + theme, sources[i]);
      var pre = document.createElement("pre");
      pre.id = "out-" + theme + "-" + i;
      pre.textContent = out.svg;
      document.body.appendChild(pre);
    }}
  }}
  document.body.setAttribute("data-done", "yes");
}})().catch(function (e) {{
  var pre = document.createElement("pre");
  pre.id = "error";
  pre.textContent = String((e && e.stack) || e);
  document.body.appendChild(pre);
}});
</script>
</body></html>
"""


def find_chrome() -> str:
    env = os.environ.get("CHROME")
    candidates = [
        env,
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise SystemExit("No Chrome or Chromium found; set CHROME to its path.")


def tidy(svg: str) -> str:
    """Give the SVG a fixed size from its viewBox (it is shown as an <img>)."""
    m = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg)
    if not m:
        raise SystemExit("mermaid returned an SVG without a viewBox")
    w, h = (round(float(m.group(3)), 1), round(float(m.group(4)), 1))
    head_end = svg.index(">")
    head = svg[:head_end]
    head = re.sub(r'\swidth="[^"]*"', "", head)
    head = re.sub(r'\sheight="[^"]*"', "", head)
    head = re.sub(r'\sstyle="[^"]*"', "", head)
    head = head.replace("<svg", f'<svg width="{w:g}" height="{h:g}"', 1)
    return head + svg[head_end:] + "\n"


def fetch_mermaid() -> None:
    """Download the pinned tarball once, keep only dist/mermaid.min.js, verify it."""
    if MERMAID.exists() and hashlib.sha256(MERMAID.read_bytes()).hexdigest() == MERMAID_SHA256:
        return
    print(f"downloading mermaid {MERMAID_VERSION} from {MERMAID_TARBALL}")
    with tempfile.TemporaryDirectory() as tmp:
        tgz = Path(tmp) / "mermaid.tgz"
        with urllib.request.urlopen(MERMAID_TARBALL, timeout=60) as response:
            tgz.write_bytes(response.read())
        with tarfile.open(tgz) as archive:
            member = archive.extractfile("package/dist/mermaid.min.js")
            if member is None:
                raise SystemExit("package/dist/mermaid.min.js is missing from the tarball")
            data = member.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != MERMAID_SHA256:
        raise SystemExit(f"mermaid {MERMAID_VERSION} from npm has sha256 {digest}, expected {MERMAID_SHA256}")
    MERMAID.parent.mkdir(parents=True, exist_ok=True)
    MERMAID.write_bytes(data)


def main() -> int:
    fetch_mermaid()
    blocks = mermaid_blocks(ROOT)
    sources = [src for _, src in blocks]
    chrome = find_chrome()
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "diagrams.html"
        page.write_text(
            PAGE.format(
                sources=json.dumps(sources).replace("</", "<\\/"),
                themes=json.dumps(THEMES).replace("</", "<\\/"),
                mermaid=MERMAID.as_uri(),
            ),
            encoding="utf-8",
        )
        argv = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={Path(tmp) / 'profile'}",
            "--allow-file-access-from-files",
            "--virtual-time-budget=60000",
            "--dump-dom",
            page.as_uri(),
        ]
        dom = subprocess.run(argv, capture_output=True, text=True, timeout=180, check=False).stdout
    err = re.search(r'<pre id="error">(.*?)</pre>', dom, flags=re.DOTALL)
    if err:
        raise SystemExit("mermaid failed: " + html.unescape(err.group(1)))
    if 'data-done="yes"' not in dom:
        raise SystemExit("Chrome did not finish rendering the diagrams")
    DIAGRAMS.mkdir(parents=True, exist_ok=True)
    keep: set[str] = set()
    for i, (chapter, src) in enumerate(blocks):
        key = diagram_key(src)
        for theme in THEMES:
            m = re.search(rf'<pre id="out-{theme}-{i}">(.*?)</pre>', dom, flags=re.DOTALL)
            if not m:
                raise SystemExit(f"no {theme} SVG for diagram {i} in {chapter}")
            path = DIAGRAMS / f"{key}-{theme}.svg"
            path.write_text(tidy(html.unescape(m.group(1))), encoding="utf-8")
            keep.add(path.name)
        print(f"{chapter}: {key} (light, dark)")
    for old in DIAGRAMS.glob("*.svg"):
        if old.name not in keep:
            old.unlink()
            print(f"removed {old.name}")
    print(
        f"{len(blocks)} diagrams rendered with mermaid {MERMAID_VERSION} into {DIAGRAMS.relative_to(ROOT)}/"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
