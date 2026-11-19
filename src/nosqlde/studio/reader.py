"""The guide reader: guide/*.md rendered to HTML on the server for the studio's Read view.

markdown-it-py (CommonMark plus tables) with raw HTML off, so a `<script>` or `<img
onerror>` in a chapter is shown as text and never runs. On top of the stock renderer:

* headings get GitHub's anchors (the ids the lessons link to) and a copy-link anchor;
* links are rewritten: another chapter becomes an in-studio route (#/read/NN/anchor), a
  repository file opens the read-only file viewer (#/file/path), and anything else opens
  in a new tab with rel="noopener noreferrer";
* a code span that names a repository file (`src/nosqlde/flatten.py`) links to the viewer;
* fenced code gets light highlighting, a copy button and, when the block is in a console
  language (see detect_console), an "Open in <console>" button. Shell and Python blocks
  never get one: the studio has no shell;
* `text` blocks are styled as program output;
* mermaid blocks become <img>s of SVGs pre-rendered by tools/render_diagrams.py, one for
  each theme, so no diagram library runs in the page and the CSP stays strict;
* tables sit in a scrollable region, and column alignment is a class, not a style
  attribute (the CSP forbids inline styles).

Each chapter is cached by modification time, so an edited chapter shows on refresh.
"""

from __future__ import annotations

import hashlib
import html
import posixpath
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.token import Token

from nosqlde.studio import repofiles
from nosqlde.studio.lessons.model import slug
from nosqlde.studio.paths import repo_root

STATIC = Path(__file__).parent / "static"
DIAGRAMS = STATIC / "diagrams"
CHAPTER_FILE = re.compile(r"^(\d\d)-[a-z0-9-]+\.md$")

#: console id -> the label on its tab (a unit test keeps this in step with runners.CONSOLES)
CONSOLE_LABELS = {
    "mongo": "MongoDB",
    "redis": "Redis",
    "cql": "Cassandra",
    "dynamodb": "DynamoDB",
    "cypher": "Neo4j",
    "duckdb": "DuckDB",
}
#: languages that are never offered to a console: the studio runs database statements only
NEVER_CONSOLE = frozenset(
    {"bash", "sh", "shell", "zsh", "console", "python", "py", "python3", "json", "yaml", "yml", "toml"}
    | {"mermaid", "diff", "ini", "dockerfile", "make", "makefile", "html", "css"}
)
LANG_LABELS = {
    "bash": "Shell",
    "sh": "Shell",
    "shell": "Shell",
    "python": "Python",
    "py": "Python",
    "json": "JSON",
    "text": "Output",
    "": "Output",
    "cypher": "Cypher",
    "sql": "SQL",
    "cql": "CQL",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "mongosh": "mongosh",
    "redis": "redis-cli",
    "yaml": "YAML",
}
CONSOLE_LANG_LABELS = {
    "mongo": "mongosh",
    "redis": "redis-cli",
    "cql": "CQL",
    "dynamodb": "PartiQL",
    "cypher": "Cypher",
    "duckdb": "SQL",
}

# ---------------------------------------------------------------- console detection


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


REDIS_COMMANDS = _words(
    """APPEND BGSAVE BITCOUNT BLPOP BRPOP CONFIG DBSIZE DECR DECRBY DEL ECHO EXISTS EXPIRE EXPIREAT
    GET GETDEL GETEX GETSET HDEL HEXISTS HGET HGETALL HINCRBY HKEYS HLEN HMGET HSET HSETNX HVALS INCR
    INCRBY INCRBYFLOAT INFO KEYS LINDEX LLEN LPOP LPUSH LRANGE LREM LSET LTRIM MEMORY MGET MSET OBJECT
    PERSIST PEXPIRE PING PTTL RENAME RPOP RPUSH SADD SCAN SCARD SDIFF SET SETEX SETNX SINTER SISMEMBER
    SMEMBERS SREM STRLEN SUNION TTL TYPE UNLINK XACK XADD XAUTOCLAIM XCLAIM XDEL XGROUP XINFO XLEN
    XPENDING XRANGE XREAD XREADGROUP XREVRANGE XTRIM ZADD ZCARD ZCOUNT ZINCRBY ZRANGE ZRANGEBYSCORE ZRANK
    ZREM ZREVRANGE ZREVRANK ZSCORE"""
)
CQL_MARKERS = re.compile(
    r"ALLOW\s+FILTERING|PRIMARY\s+KEY\s*\(\s*\(|CLUSTERING\s+ORDER\s+BY|USING\s+TTL|USING\s+TIMESTAMP"
    r"|CREATE\s+KEYSPACE|\)\s*IF\s+(NOT\s+)?EXISTS|\bIF\s+EXISTS\s*;|^\s*CONSISTENCY\b|^\s*TRACING\s+O[NF]"
    r"|\btoken\s*\(|\btimeuuid\b",
    re.MULTILINE,
)
DUCKDB_MARKERS = re.compile(r"read_parquet\s*\(|FROM\s+'lake/|\bSUMMARIZE\b|::\w+", re.IGNORECASE)
SQL_START = re.compile(
    r"^(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|BEGIN|TRUNCATE|USE|WITH|FROM|DESCRIBE|"
    r"SUMMARIZE|EXPLAIN|TRACING|CONSISTENCY)\b"
)
CYPHER_START = re.compile(r"^(OPTIONAL\s+MATCH|MATCH|MERGE|UNWIND|CREATE|CALL|PROFILE|EXPLAIN|RETURN)\b")
CYPHER_PATTERN = re.compile(r"\(\w*:\w+|\)\s*<?-\s*\[|\]\s*-\s*>?\s*\(|\)\s*-->|<--\s*\(")
MONGO_START = re.compile(
    r"^db\.(\w+\.\w+\s*\(|getCollection\s*\(|getCollectionNames\s*\(|createCollection\s*\()"
)
COMMENT_LINE = re.compile(r"^\s*(--|//|#)")


def _statement_lines(code: str) -> list[str]:
    return [line for line in code.splitlines() if line.strip() and not COMMENT_LINE.match(line)]


def detect_console(lang: str, code: str, chapter: int | None = None) -> str | None:
    """The console a code block belongs in, or None (copy only).

    A tagged block maps by its tag: cypher to Neo4j, cql to Cassandra, mongosh or js to
    MongoDB, sql to DuckDB (or to Cassandra when it uses CQL-only syntax or is in chapter 4,
    where the guide writes CQL as sql). An untagged or `text` block is offered only when its
    content is unambiguous: `db.x.find(`, Cypher with a `MATCH (` pattern, CQL with
    `ALLOW FILTERING` and the like, DuckDB reading the lake, or redis-cli commands on every
    line. Program output (`x -> y` lines) and abridged snippets (a `...` line) never
    qualify. Shell, Python and JSON blocks never get a console.
    """
    lang = (lang or "").strip().lower()
    if lang in NEVER_CONSOLE:
        return None
    if re.search(r"^\s*(\.\.\.|…)\s*$", code, re.M):
        return None  # an abridged snippet: running it would only fail
    if lang == "cypher":
        return "cypher"
    if lang == "cql":
        return "cql"
    if lang in ("mongosh", "mongo", "mongodb", "js", "javascript"):
        return "mongo"
    if lang in ("redis", "redis-cli"):
        return "redis"
    if lang == "partiql":
        return "dynamodb"
    if lang in ("sql", "duckdb"):
        if lang == "sql" and (CQL_MARKERS.search(code) or chapter == 4):
            return "cql"
        return "duckdb"
    if lang not in ("", "text", "txt", "plain"):
        return None
    return _detect_by_content(code)


def _detect_by_content(code: str) -> str | None:
    lines = _statement_lines(code)
    if not lines:
        return None
    if re.search(r"\s->\s", code) or "..." in code or "…" in code:
        return None  # program output ("x -> y"), or an abridged statement
    first = lines[0].strip()
    if MONGO_START.match(first):
        if all(re.match(r"^(db\.|\s|[}\])].*)", line) for line in lines):
            return "mongo"
        return None
    if CYPHER_START.match(first) and CYPHER_PATTERN.search(code):
        return "cypher"
    if SQL_START.match(first):
        if CQL_MARKERS.search(code):
            return "cql"
        if DUCKDB_MARKERS.search(code):
            return "duckdb"
        return None  # SQL, but which database is not clear
    words = [line.split()[0] for line in lines]
    if all(w in REDIS_COMMANDS for w in words) and not any(";" in line for line in lines):
        return "redis"
    return None


# ---------------------------------------------------------------- highlighting

_STRING = r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\""
_NUMBER = r"\b\d+(?:\.\d+)?\b"
SQL_KEYWORDS = _words(
    """SELECT FROM WHERE AND OR NOT IN IS NULL AS ON JOIN LEFT RIGHT INNER OUTER FULL GROUP BY ORDER
    HAVING LIMIT OFFSET DISTINCT COUNT SUM AVG MIN MAX INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE
    VIEW INDEX DROP ALTER PRIMARY KEY WITH RECURSIVE UNION ALL CASE WHEN THEN ELSE END ASC DESC BETWEEN
    LIKE EXISTS IF ALLOW FILTERING CLUSTERING USING TTL TIMESTAMP KEYSPACE BEGIN BATCH APPLY TRUNCATE
    COUNTER TRACING CONSISTENCY DESCRIBE EXPLAIN ANALYZE OVER PARTITION QUALIFY FILTER CAST TRUE FALSE"""
)
CYPHER_KEYWORDS = _words(
    """MATCH OPTIONAL WHERE RETURN WITH UNWIND MERGE CREATE SET DELETE DETACH REMOVE ON AS ORDER BY
    LIMIT SKIP DISTINCT AND OR NOT IN IS NULL CALL YIELD UNION ALL CASE WHEN THEN ELSE END PROFILE
    EXPLAIN CONSTRAINT FOR REQUIRE UNIQUE INDEX EXISTS COUNT COLLECT TRUE FALSE ASC DESC"""
)
CODE_KEYWORDS = _words(
    """def return if elif else for while in not and or is None True False import from as with class try
    except finally raise lambda yield true false null new const let var function"""
)
_TOKENS = {
    "sql": re.compile(rf"(?P<c>--[^\n]*|//[^\n]*)|(?P<s>{_STRING})|(?P<n>{_NUMBER})|(?P<w>[A-Za-z_]\w*)"),
    "cypher": re.compile(
        rf"(?P<c>//[^\n]*)|(?P<s>{_STRING})|(?P<p>\$\w+)|(?P<l>(?<=[(\[\w]):[A-Za-z_]\w*)"
        rf"|(?P<n>{_NUMBER})|(?P<w>[A-Za-z_]\w*)"
    ),
    "bash": re.compile(rf"(?P<c>(?<![\w$])#[^\n]*)|(?P<s>{_STRING})"),
    "code": re.compile(
        rf"(?P<c>(?<![\w$'\"])#[^\n]*|//[^\n]*)|(?P<s>{_STRING})|(?P<n>{_NUMBER})|(?P<w>[A-Za-z_$][\w$]*)"
    ),
}
_FAMILY = {
    "sql": "sql",
    "cql": "sql",
    "duckdb": "sql",
    "cypher": "cypher",
    "bash": "bash",
    "sh": "bash",
    "shell": "bash",
    "python": "code",
    "py": "code",
    "json": "code",
    "js": "code",
    "javascript": "code",
    "mongosh": "code",
}
_CONSOLE_FAMILY = {"cql": "sql", "duckdb": "sql", "cypher": "cypher", "mongo": "code", "dynamodb": "sql"}


def highlight(code: str, family: str | None) -> str:
    """Escaped HTML with a few <span class="tok-*"> for comments, strings, numbers and keywords."""
    pattern = _TOKENS.get(family or "")
    if pattern is None:
        return html.escape(code, quote=False)
    keywords = SQL_KEYWORDS if family == "sql" else CYPHER_KEYWORDS if family == "cypher" else CODE_KEYWORDS
    out: list[str] = []
    pos = 0
    for m in pattern.finditer(code):
        kind = m.lastgroup or ""
        text = m.group()
        if kind == "w":
            word = text.upper() if family in ("sql", "cypher") else text
            if word not in keywords or (family in ("sql", "cypher") and text != text.upper()):
                continue
            kind = "k"
        out.append(html.escape(code[pos : m.start()], quote=False))
        out.append(f'<span class="tok-{kind}">{html.escape(text, quote=False)}</span>')
        pos = m.end()
    out.append(html.escape(code[pos:], quote=False))
    return "".join(out)


# ---------------------------------------------------------------- diagrams


def diagram_key(source: str) -> str:
    """The pre-rendered SVGs' file name stem for a mermaid source (its content hash)."""
    return hashlib.sha256(source.strip().encode()).hexdigest()[:16]


def mermaid_blocks(root: Path | None = None) -> list[tuple[str, str]]:
    """(chapter file, source) of every mermaid block in the guide, in order."""
    out: list[tuple[str, str]] = []
    for path in chapter_paths(root):
        tokens = _parser().parse(path.read_text(encoding="utf-8"))
        out.extend((path.name, t.content) for t in tokens if t.type == "fence" and _lang(t) == "mermaid")
    return out


def diagram_files(source: str) -> dict[str, Path]:
    key = diagram_key(source)
    return {theme: DIAGRAMS / f"{key}-{theme}.svg" for theme in ("light", "dark")}


def _svg_size(path: Path) -> tuple[str, str] | None:
    head = path.read_text(encoding="utf-8")[:2000]
    w = re.search(r'<svg[^>]*?\swidth="([\d.]+)"', head)
    h = re.search(r'<svg[^>]*?\sheight="([\d.]+)"', head)
    return (w.group(1), h.group(1)) if w and h else None


def diagram_alt(source: str) -> str:
    """A text alternative: the kind of diagram and its labels, in source order."""
    labels: list[str] = []
    for m in re.finditer(r'"([^"]+)"|\|([^|"]+)\|', source):
        text = re.sub(r"<br\s*/?>", " ", m.group(1) or m.group(2) or "")
        text = " ".join(text.split())
        if text and text not in labels:
            labels.append(text)
    kind = "Flowchart" if source.lstrip().startswith(("flowchart", "graph")) else "Diagram"
    return f"{kind}: " + "; ".join(labels) if labels else kind


# ---------------------------------------------------------------- the renderer


def _lang(token: Token) -> str:
    return (token.info or "").strip().split(" ")[0].lower()


def _inline_text(token: Token | None) -> str:
    if token is None or not token.children:
        return token.content if token is not None else ""
    return "".join(
        " " if c.type in ("softbreak", "hardbreak") else c.content
        for c in token.children
        if c.type in ("text", "code_inline", "softbreak", "hardbreak")
    )


def _attr(name: str, value: str) -> str:
    return f' {name}="{html.escape(value, quote=True)}"'


@dataclass
class Env:
    chapter: int
    root: Path
    chapters: dict[int, str]  # number -> file name
    toc: list[dict[str, Any]] = field(default_factory=list)
    ids: dict[str, int] = field(default_factory=dict)
    links: list[str] = field(default_factory=list)  # every in-studio route written
    title: str = ""


def _anchors(state: StateCore) -> None:
    """Give each heading GitHub's id (deduplicated with -1, -2) and record the TOC."""
    env = state.env.get("reader")
    if not isinstance(env, Env):
        return
    tokens = state.tokens
    for i, tok in enumerate(tokens):
        if tok.type != "heading_open":
            continue
        text = _inline_text(tokens[i + 1] if i + 1 < len(tokens) else None).strip()
        base = slug(text) or "section"
        n = env.ids.get(base, 0)
        env.ids[base] = n + 1
        hid = base if n == 0 else f"{base}-{n}"
        tok.attrSet("id", hid)
        level = int(tok.tag[1])
        if level == 1 and not env.title:
            env.title = text
        if level in (2, 3):
            env.toc.append({"level": level, "id": hid, "text": text})
    for tok in tokens:  # table alignment as a class: the CSP forbids style attributes
        if tok.type in ("th_open", "td_open") and tok.attrs.get("style"):
            align = str(tok.attrs.pop("style")).replace("text-align:", "").strip()
            tok.attrSet("class", f"align-{align}")


def chapter_route(number: int, anchor: str = "") -> str:
    return f"#/read/{number:02d}" + (f"/{anchor}" if anchor else "")


def classify_link(href: str, env: Env) -> tuple[str, str]:
    """(kind, href): "chapter" and "file" are in-studio routes, "external" opens in a new
    tab, "broken" is a relative link to nothing the studio can show."""
    parts = urlsplit(href)
    if parts.scheme in ("http", "https", "mailto") or href.startswith("//"):
        return "external", href
    if parts.scheme:
        return "broken", ""
    anchor = unquote(parts.fragment)
    if not parts.path:
        return "chapter", chapter_route(env.chapter, anchor)
    target = posixpath.normpath(posixpath.join("guide", unquote(parts.path)))
    m = re.match(r"^guide/(\d\d)-[^/]+\.md$", target)
    if m and int(m.group(1)) in env.chapters and env.chapters[int(m.group(1))] == target[6:]:
        return "chapter", chapter_route(int(m.group(1)), anchor)
    if target.startswith("../") or target == "..":
        return "broken", ""
    if repofiles.viewable(target, env.root):
        return "file", "#/file/" + target
    return "broken", ""


def _render_link_open(self: Any, tokens: list[Token], idx: int, options: Any, env: dict[str, Any]) -> str:
    tok = tokens[idx]
    reader: Env = env["reader"]
    kind, href = classify_link(str(tok.attrGet("href") or ""), reader)
    if kind == "external":
        return (
            f'<a class="ext"{_attr("href", href)} target="_blank" rel="noopener noreferrer"'
            ' title="Opens in a new tab">'
        )
    if kind == "broken":
        return '<a class="broken" title="This link points outside what the studio can show">'
    reader.links.append(href)
    return f'<a class="{kind}-link"{_attr("href", href)}>'


def _render_code_inline(self: Any, tokens: list[Token], idx: int, options: Any, env: dict[str, Any]) -> str:
    content = tokens[idx].content
    code = f"<code>{html.escape(content, quote=False)}</code>"
    reader: Env = env["reader"]
    path = content.strip()
    if _inside_link(tokens, idx) or not re.fullmatch(r"[\w.-]+(/[\w.-]+)*/?", path):
        return code
    if "/" not in path and path not in repofiles.ALLOWED_FILES:
        return code
    m = re.fullmatch(r"guide/(\d\d)-[^/]+\.md", path)
    if m and int(m.group(1)) in reader.chapters:
        href = chapter_route(int(m.group(1)))
    elif repofiles.viewable(path, reader.root):
        href = "#/file/" + path.rstrip("/")
    else:
        return code
    reader.links.append(href)
    return f'<a class="file-link"{_attr("href", href)}>{code}</a>'


def _inside_link(tokens: list[Token], idx: int) -> bool:
    for t in reversed(tokens[:idx]):
        if t.type == "link_close":
            return False
        if t.type == "link_open":
            return True
    return False


def _render_heading_close(self: Any, tokens: list[Token], idx: int, options: Any, env: dict[str, Any]) -> str:
    reader: Env = env["reader"]
    opener = next(t for t in reversed(tokens[:idx]) if t.type == "heading_open")
    hid = str(opener.attrGet("id") or "")
    text = _inline_text(tokens[idx - 1]).strip()
    href = chapter_route(reader.chapter, hid)
    return (
        f'<a class="h-anchor"{_attr("href", href)}{_attr("aria-label", "Copy a link to: " + text)}'
        f' data-anchor="{html.escape(hid)}">#</a></{tokens[idx].tag}>\n'
    )


def _render_table_open(self: Any, tokens: list[Token], idx: int, options: Any, env: dict[str, Any]) -> str:
    return '<div class="table-wrap" tabindex="0" role="region" aria-label="Table">\n<table>\n'


def _render_table_close(self: Any, tokens: list[Token], idx: int, options: Any, env: dict[str, Any]) -> str:
    return "</table>\n</div>\n"


def _render_image(self: Any, tokens: list[Token], idx: int, options: Any, env: dict[str, Any]) -> str:
    tok = tokens[idx]
    reader: Env = env["reader"]
    alt = _inline_text(tok) or tok.content
    src = str(tok.attrGet("src") or "")
    parts = urlsplit(src)
    if parts.scheme or src.startswith("//"):
        # the CSP loads images from the studio only; an outside image becomes a link
        return (
            f'<a class="ext"{_attr("href", src)} target="_blank" rel="noopener noreferrer">'
            f"Image: {html.escape(alt or src)}</a>"
        )
    target = posixpath.normpath(posixpath.join("guide", unquote(parts.path)))
    try:
        repofiles.image(target, reader.root)
    except repofiles.FileRefused:
        return f'<span class="broken">[image: {html.escape(alt or src)}]</span>'
    return f'<img{_attr("src", "/repo-img/" + target)}{_attr("alt", alt)} loading="lazy">'


def _render_fence(self: Any, tokens: list[Token], idx: int, options: Any, env: dict[str, Any]) -> str:
    tok = tokens[idx]
    reader: Env = env["reader"]
    lang = _lang(tok)
    code = tok.content
    if lang == "mermaid":
        return _render_mermaid(code)
    console = detect_console(lang, code, reader.chapter)
    family = _CONSOLE_FAMILY.get(console or "") or _FAMILY.get(lang)
    label = CONSOLE_LANG_LABELS[console] if console else LANG_LABELS.get(lang, lang or "Output")
    is_output = console is None and lang in ("", "text", "txt", "plain", "output")
    classes = "codeblock" + (" output" if is_output else "") + (f" acc-{console}" if console else "")
    head = [f'<span class="codeblock-lang">{html.escape(label)}</span>', '<span class="codeblock-actions">']
    head.append('<button type="button" class="btn small ghost" data-action="copy">Copy</button>')
    if console:
        head.append(
            f'<button type="button" class="btn small" data-action="console" data-console="{console}"'
            f"{_attr('aria-label', 'Open this ' + label + ' in the ' + CONSOLE_LABELS[console] + ' console')}>"
            f"Open in {CONSOLE_LABELS[console]}</button>"
        )
    head.append("</span>")
    return (
        f'<div class="{classes}"{_attr("data-lang", lang or "text")}>'
        f'<div class="codeblock-head">{"".join(head)}</div>'
        f'<pre tabindex="0"><code>{highlight(code, family)}</code></pre></div>\n'
    )


def _render_mermaid(source: str) -> str:
    files = diagram_files(source)
    alt = diagram_alt(source)
    src_html = (
        '<details class="diagram-source"><summary>Diagram source (Mermaid)</summary>'
        f'<pre tabindex="0"><code>{html.escape(source, quote=False)}</code></pre></details>'
    )
    if not all(p.is_file() for p in files.values()):
        return (
            '<figure class="diagram missing"><p class="callout">This diagram has not been rendered yet: '
            "run <code>make diagrams</code>. Its source:</p>"
            f'<pre tabindex="0"><code>{html.escape(source, quote=False)}</code></pre></figure>\n'
        )
    imgs = []
    for theme, path in files.items():
        size = _svg_size(path)
        dims = _attr("width", size[0]) + _attr("height", size[1]) if size else ""
        imgs.append(
            f'<img class="diagram-{theme}"{_attr("src", "/static/diagrams/" + path.name)}'
            f'{_attr("alt", alt)}{dims} decoding="async">'
        )
    return (
        f'<figure class="diagram"><div class="diagram-scroll" tabindex="0" role="group"{_attr("aria-label", alt)}>'
        f"{''.join(imgs)}</div>{src_html}</figure>\n"
    )


def _parser() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
    md.enable(["table", "strikethrough"])
    return md


def _renderer() -> MarkdownIt:
    md = _parser()
    md.core.ruler.push("reader_anchors", _anchors)
    for name, fn in {
        "link_open": _render_link_open,
        "code_inline": _render_code_inline,
        "heading_close": _render_heading_close,
        "table_open": _render_table_open,
        "table_close": _render_table_close,
        "image": _render_image,
        "fence": _render_fence,
        "code_block": _render_fence,
    }.items():
        md.add_render_rule(name, fn)
    return md


# ---------------------------------------------------------------- chapters


def guide_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "guide"


def chapter_paths(root: Path | None = None) -> list[Path]:
    d = guide_dir(root)
    return sorted(p for p in d.iterdir() if CHAPTER_FILE.match(p.name)) if d.is_dir() else []


def _title_of(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return re.sub(r"^\d+\.\s*", "", line[2:].strip()).replace("`", "")
    return path.stem


def chapter_list(root: Path | None = None) -> list[dict[str, Any]]:
    return [
        {"number": int(p.name[:2]), "id": p.name[:2], "file": p.name, "title": _title_of(p)}
        for p in chapter_paths(root)
    ]


@dataclass(frozen=True)
class Rendered:
    number: int
    file: str
    title: str
    html: str
    toc: list[dict[str, Any]]
    ids: frozenset[str]
    links: tuple[str, ...]
    sections: tuple[tuple[str, str, str], ...]  # (anchor, heading, plain text)


_cache: dict[Path, tuple[tuple[int, int, int], Rendered]] = {}
_cache_lock = threading.Lock()


def _diagrams_stamp() -> int:
    try:
        return DIAGRAMS.stat().st_mtime_ns
    except OSError:
        return 0


def render(number: int, root: Path | None = None) -> Rendered:
    """Render guide chapter `number`; KeyError if there is no such chapter."""
    root = root or repo_root()
    paths = {int(p.name[:2]): p for p in chapter_paths(root)}
    path = paths[number]
    st = path.stat()
    stamp = (st.st_mtime_ns, st.st_size, _diagrams_stamp())
    with _cache_lock:
        hit = _cache.get(path)
        if hit and hit[0] == stamp:
            return hit[1]
    source = path.read_text(encoding="utf-8")
    env = Env(chapter=number, root=root, chapters={n: p.name for n, p in paths.items()})
    md = _renderer()
    tokens = md.parse(source, {"reader": env})
    body = md.renderer.render(tokens, md.options, {"reader": env})
    result = Rendered(
        number=number,
        file=path.name,
        title=re.sub(r"^\d+\.\s*", "", env.title),
        html=body,
        toc=env.toc,
        ids=frozenset(_ids(tokens)),
        links=tuple(env.links),
        sections=tuple(_sections(tokens)),
    )
    with _cache_lock:
        _cache[path] = (stamp, result)
    return result


def _ids(tokens: list[Token]) -> list[str]:
    return [str(t.attrGet("id")) for t in tokens if t.type == "heading_open" and t.attrGet("id")]


def _sections(tokens: list[Token]) -> list[tuple[str, str, str]]:
    """(anchor, heading, plain text) per heading, for search."""
    out: list[tuple[str, str, str]] = []
    anchor, heading = "", ""
    text: list[str] = []  # text before the first heading belongs to the title
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open":
            if heading or text:
                out.append((anchor, heading, " ".join(text)))
            anchor, heading = str(tok.attrGet("id") or ""), _inline_text(tokens[i + 1]).strip()
            text = []
            i += 3
            continue
        if tok.type == "inline":
            text.append(_inline_text(tok))
        elif tok.type in ("fence", "code_block") and _lang(tok) != "mermaid":
            text.append(tok.content)
        i += 1
    if heading or text:
        out.append((anchor, heading, " ".join(text)))
    return out


def chapter_json(number: int, root: Path | None = None) -> dict[str, Any]:
    r = render(number, root)
    chapters = chapter_list(root)
    numbers = [c["number"] for c in chapters]
    i = numbers.index(number)
    return {
        "number": r.number,
        "id": f"{r.number:02d}",
        "file": r.file,
        "title": r.title,
        "html": r.html,
        "toc": r.toc,
        "prev": chapters[i - 1] if i > 0 else None,
        "next": chapters[i + 1] if i + 1 < len(chapters) else None,
    }


def search(query: str, root: Path | None = None, limit: int = 25) -> list[dict[str, Any]]:
    """Sections whose heading or text contain every word of the query; headings rank first."""
    terms = [t for t in re.split(r"\s+", query.strip().lower()) if t][:8]
    if not terms or sum(len(t) for t in terms) < 2:
        return []
    scored: list[tuple[int, int, int, dict[str, Any]]] = []
    for order, c in enumerate(chapter_list(root)):
        r = render(c["number"], root)
        for pos, (anchor, heading, text) in enumerate(r.sections):
            hay_h, hay_t = heading.lower(), text.lower()
            if not all(t in hay_h or t in hay_t for t in terms):
                continue
            score = sum(3 for t in terms if t in hay_h) + sum(min(hay_t.count(t), 5) for t in terms)
            scored.append(
                (
                    -score,
                    order,
                    pos,
                    {
                        "chapter": r.number,
                        "chapter_title": r.title,
                        "anchor": anchor,
                        "heading": heading or r.title,
                        "snippet": _snippet(text, terms),
                    },
                )
            )
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [x[3] for x in scored[:limit]]


def _snippet(text: str, terms: list[str], width: int = 80) -> str:
    flat = " ".join(text.split())
    low = flat.lower()
    hits = [low.find(t) for t in terms if low.find(t) >= 0]
    if not hits:
        return flat[: 2 * width] + ("..." if len(flat) > 2 * width else "")
    at = min(hits)
    start = max(0, at - width)
    end = min(len(flat), at + width)
    return ("..." if start else "") + flat[start:end] + ("..." if end < len(flat) else "")
