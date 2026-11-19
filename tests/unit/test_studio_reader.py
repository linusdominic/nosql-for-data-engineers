"""The guide reader and the file viewer: every chapter renders, every internal link and
anchor resolves inside the studio, raw HTML is escaped, the file viewer stays inside the
repository, and code blocks go to the right console (or to none)."""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nosqlde.studio import reader, repofiles
from nosqlde.studio.lessons.model import GUIDE_FILES
from nosqlde.studio.progress import Progress
from nosqlde.studio.registry import LESSONS
from nosqlde.studio.runners import CONSOLES
from nosqlde.studio.server import create_app

ROOT = Path(__file__).resolve().parents[2]
CHAPTERS = [c["number"] for c in reader.chapter_list(ROOT)]
PORT = 8790
TOKEN = "t0ken-for-reader-tests"
H = {"X-Studio-Token": TOKEN}


class Links(HTMLParser):
    """Every <a> and <img> with its attributes, and every tag name."""

    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict[str, str | None]] = []
        self.images: list[dict[str, str | None]] = []
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attrs.extend(attrs)
        if tag == "a":
            self.anchors.append(dict(attrs))
        if tag == "img":
            self.images.append(dict(attrs))


def parsed(html: str) -> Links:
    p = Links()
    p.feed(html)
    return p


def write_guide(root: Path, files: dict[str, str]) -> Path:
    (root / "guide").mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


# ---------------------------------------------------------------- the real guide


def test_the_guide_has_chapters_0_to_8() -> None:
    assert list(range(9)) == CHAPTERS
    assert [c["file"] for c in reader.chapter_list(ROOT)] == [GUIDE_FILES[n] for n in range(9)]


@pytest.mark.parametrize("number", CHAPTERS)
def test_every_chapter_renders(number: int) -> None:
    r = reader.render(number, ROOT)
    assert r.title and r.html.count("<h1") == 1
    assert len(r.toc) >= 5 and all(t["level"] in (2, 3) for t in r.toc)
    assert len(r.ids) == len(re.findall(r"<h[1-6] id=", r.html)), "heading ids must be unique"
    p = parsed(r.html)
    assert "script" not in p.tags and "style" not in p.tags
    assert not [a for a, _ in p.attrs if a == "style" or a.startswith("on")], "no inline style or handlers"
    body = reader.chapter_json(number, ROOT)
    assert body["id"] == f"{number:02d}" and body["html"] == r.html
    assert (body["prev"] is None) == (number == 0) and (body["next"] is None) == (number == 8)


@pytest.mark.parametrize("number", CHAPTERS)
def test_every_internal_link_and_anchor_resolves(number: int) -> None:
    r = reader.render(number, ROOT)
    p = parsed(r.html)
    assert not [a for a in p.anchors if "broken" in (a.get("class") or "")], "a link to nothing"
    for a in p.anchors:
        href = a.get("href") or ""
        if href.startswith("#/read/"):
            m = re.fullmatch(r"#/read/(\d\d)(?:/(.+))?", href)
            assert m, href
            target = int(m.group(1))
            assert target in CHAPTERS, href
            if m.group(2):
                assert m.group(2) in reader.render(target, ROOT).ids, f"no heading {href}"
        elif href.startswith("#/file/"):
            repofiles.read(href[len("#/file/") :], ROOT)  # raises if refused or missing
        else:
            assert href.startswith(("https://", "http://")), href
            assert a.get("target") == "_blank", href
            assert set((a.get("rel") or "").split()) >= {"noopener", "noreferrer"}, href
    for link in r.links:
        assert link.startswith(("#/read/", "#/file/")), link


def test_lesson_guide_links_land_on_rendered_headings() -> None:
    for lesson in LESSONS.values():
        for ref in [lesson.guide, *(s.guide for s in lesson.steps)]:
            assert ref.anchor in reader.render(ref.chapter, ROOT).ids, (ref.chapter, ref.heading)
            assert ref.public()["anchor"] == ref.anchor


def test_code_spans_naming_repository_files_link_to_the_viewer() -> None:
    html = reader.render(2, ROOT).html
    assert (
        '<a class="file-link" href="#/file/src/nosqlde/flatten.py"><code>src/nosqlde/flatten.py</code></a>'
        in html
    )
    # lake/ output is not in the viewer, so it stays plain code
    assert 'href="#/file/lake' not in reader.render(5, ROOT).html


def test_every_mermaid_diagram_is_pre_rendered_for_both_themes() -> None:
    blocks = reader.mermaid_blocks(ROOT)
    assert len(blocks) == 3
    for _, source in blocks:
        for path in reader.diagram_files(source).values():
            assert path.is_file(), f"run make diagrams ({path.name} is missing)"
            svg = path.read_text(encoding="utf-8")
            assert svg.startswith("<svg") and "<script" not in svg.lower()
    for number in (1, 7, 8):
        p = parsed(reader.render(number, ROOT).html)
        classes = {img.get("class") for img in p.images}
        assert classes == {"diagram-light", "diagram-dark"}
        assert all((img.get("alt") or "").startswith("Flowchart: ") for img in p.images)


def test_tables_are_scrollable_and_text_blocks_are_output() -> None:
    html = reader.render(1, ROOT).html
    assert '<div class="table-wrap" tabindex="0" role="region" aria-label="Table">' in html
    assert '<div class="codeblock output" data-lang="text">' in reader.render(3, ROOT).html


def test_console_buttons_in_the_guide() -> None:
    found = {
        n: re.findall(r'data-action="console" data-console="(\w+)"', reader.render(n, ROOT).html)
        for n in CHAPTERS
    }
    assert found[4] == ["cql"]  # the CREATE TABLE written as sql in chapter 4 is CQL
    assert found[6] == ["cypher", "duckdb", "cypher"]  # the abridged UNWIND load is copy only
    for n in CHAPTERS:
        html = reader.render(n, ROOT).html
        for block in re.findall(
            r'<div class="codeblock[^"]*" data-lang="(bash|python|json)">.*?</div></div>', html
        ):
            assert "data-console" not in block


def test_search_finds_sections() -> None:
    hits = reader.search("allow filtering", ROOT)
    assert hits and hits[0]["chapter"] == 4 and hits[0]["anchor"] == "why-allow-filtering-is-a-trap"
    assert all(h["anchor"] in reader.render(h["chapter"], ROOT).ids for h in hits)
    assert reader.search("x", ROOT) == []
    assert reader.search("zzzz-not-in-the-guide", ROOT) == []


def test_console_labels_match_the_consoles() -> None:
    assert {k: v.label for k, v in CONSOLES.items()} == reader.CONSOLE_LABELS


# ---------------------------------------------------------------- escaping and link rules

HOSTILE = """# Title <script>alert(1)</script>

<script>alert(2)</script>

<img src=x onerror=alert(3)>

Inline <b onclick="alert(4)">bold</b> and <iframe src="http://evil.example"></iframe>.

[js](javascript:alert(5)) [data](data:text/html;base64,PHNjcmlwdD4=) [vb](vbscript:x)

## Section `<style>` "quotes"

| a | b |
|--:|:-:|
| <u>1</u> | 2 |

```cypher
MATCH (n) RETURN "</code></pre><script>alert(6)</script>"
```

```text
<script>alert(7)</script>
```

![pic](https://evil.example/track.png)
"""


def test_raw_html_is_escaped_and_never_runs(tmp_path: Path) -> None:
    root = write_guide(tmp_path, {"guide/00-hostile.md": HOSTILE})
    html = reader.render(0, root).html
    p = parsed(html)
    assert not {"script", "iframe", "u", "b", "style"} & set(p.tags)
    assert not [a for a, _ in p.attrs if a.startswith("on") or a == "style"]
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(3)&gt;" in html
    assert not [
        a for a in p.anchors if re.match(r"\s*(javascript|data|vbscript):", a.get("href") or "", re.I)
    ]
    assert 'class="align-right"' in html and 'class="align-center"' in html
    assert p.images == [], "an outside image is a link, never loaded"
    ext = [a for a in p.anchors if (a.get("href") or "").startswith("https://evil.example")]
    assert ext and ext[0]["rel"] == "noopener noreferrer" and ext[0]["target"] == "_blank"


def test_relative_links_become_studio_routes(tmp_path: Path) -> None:
    root = write_guide(
        tmp_path,
        {
            "guide/00-a.md": (
                "# A\n\n## First part\n\n[next](01-b.md#streams) [here](#first-part) "
                "[code](../src/pkg/mod.py) [dir](../exercises/) [secret](../.git/config) "
                "[out](../../etc/passwd) [missing](02-nope.md) [readme](../README.md)\n\n"
                "Files: `src/pkg/mod.py`, `guide/01-b.md`, `.env`, `lake/x.parquet`.\n\n"
                "![diagram](img/flow.png) ![away](../../outside.png)\n"
            ),
            "guide/01-b.md": "# B\n\n## Streams\n\ntext\n",
            "guide/img/flow.png": "png",
            "src/pkg/mod.py": "x = 1\n",
            "exercises/ex.py": "y = 2\n",
            "README.md": "# readme\n",
            ".git/config": "[core]\n",
        },
    )
    r = reader.render(0, root)
    p = parsed(r.html)
    hrefs = {a.get("href") for a in p.anchors if a.get("href")}
    assert {
        "#/read/01/streams",
        "#/read/00/first-part",
        "#/file/src/pkg/mod.py",
        "#/file/exercises",
        "#/file/README.md",
        "#/read/01",
    } <= hrefs
    assert not [h for h in hrefs if ".git" in (h or "") or "passwd" in (h or "") or "02-nope" in (h or "")]
    assert len([a for a in p.anchors if "broken" in (a.get("class") or "")]) == 3
    assert [i.get("src") for i in p.images] == ["/repo-img/guide/img/flow.png"]
    assert "[image: away]" in r.html


# ---------------------------------------------------------------- the file viewer


@pytest.mark.parametrize(
    "path",
    [
        "",
        "..",
        "../README.md",
        "../../etc/passwd",
        "guide/../../etc/passwd",
        "src/../../etc/passwd",
        "src/../.git/config",
        "/etc/passwd",
        "//etc/passwd",
        "C:/Windows/win.ini",
        "~/.ssh/id_rsa",
        "src\\nosqlde\\config.py",
        "src/nosqlde/./config.py",
        ".git/config",
        ".env",
        ".venv/pyvenv.cfg",
        ".studio/progress.json",
        "src/.hidden",
        "lake/capstone/warehouse.duckdb",
        "uv.lock",
        "src/nosqlde/studio/lessons/ch02.py",
        "src/nosqlde/__pycache__",
        "guide/00-setup.md\x00.png",
    ],
)
def test_file_viewer_refuses_paths_outside_what_it_shows(path: str) -> None:
    with pytest.raises(repofiles.FileRefused) as err:
        repofiles.read(path, ROOT)
    assert err.value.status in (400, 403, 404)


def test_file_viewer_reads_files_and_directories() -> None:
    f = repofiles.read("src/nosqlde/flatten.py", ROOT)
    assert f["kind"] == "file" and "def flatten_document" in f["text"] and f["lines"] > 10
    d = repofiles.read("src/nosqlde/labs/", ROOT)
    assert d["kind"] == "dir" and "src/nosqlde/labs/ch02_mongodb.py" in [e["path"] for e in d["entries"]]
    names = [e["name"] for e in repofiles.read("src/nosqlde/studio", ROOT)["entries"]]
    assert "lessons" not in names and "__pycache__" not in names and "reader.py" in names
    assert repofiles.read("Makefile", ROOT)["text"].startswith("#")


def test_file_viewer_does_not_follow_symlinks_out(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (root / "src").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]", encoding="utf-8")
    os.symlink(outside, root / "src" / "away")
    os.symlink(root / ".git", root / "src" / "git")
    (root / "src" / "ok.py").write_text("ok = 1\n", encoding="utf-8")
    (root / "src" / "blob.bin").write_bytes(b"\x00\x01\xff")
    for path in ("src/away/secret.txt", "src/git/config"):
        with pytest.raises(repofiles.FileRefused) as err:
            repofiles.read(path, root)
        assert err.value.status == 400
    with pytest.raises(repofiles.FileRefused) as err:
        repofiles.read("src/blob.bin", root)
    assert err.value.status == 415
    assert [e["name"] for e in repofiles.read("src", root)["entries"]] == ["blob.bin", "ok.py"]


# ---------------------------------------------------------------- console detection

DETECT = [
    # tagged blocks map by their tag
    ("cypher", "MATCH (n) RETURN n", None, "cypher"),
    ("cql", "SELECT * FROM t;", None, "cql"),
    ("js", "db.applications.find({})", None, "mongo"),
    ("mongosh", "db.loans.countDocuments()", None, "mongo"),
    ("sql", "SELECT count(*) FROM 'lake/capstone/marts/fct_loan.parquet'", 7, "duckdb"),
    ("sql", "SELECT e1.a FROM edges e1 JOIN edges e2 ON e1.v = e2.v", 6, "duckdb"),
    ("sql", "SELECT * FROM payments_by_method WHERE amount_cents > 1 ALLOW FILTERING;", None, "cql"),
    ("sql", "CREATE TABLE payments_by_loan (loan_id text, PRIMARY KEY ((loan_id)));", 4, "cql"),
    # never a console: the studio has no shell or Python
    ("bash", "make up-02\nmake lab-02", None, None),
    ("python", '[{"$match": {"status": "x"}}]', None, None),
    ("json", '{"_id": "A0000006"}', None, None),
    ("bash", "SELECT 1", None, None),
    # untagged or text: only when unambiguous
    ("", "db.applications.find({status: 'funded'}).limit(3)", None, "mongo"),
    ("text", "db.loans.aggregate([\n  {$group: {_id: '$product'}}\n])", None, "mongo"),
    ("text", "MATCH (a:Application)-[:USES_PHONE]->(p:Phone)\nRETURN p.number, count(*)", None, "cypher"),
    ("text", "SELECT * FROM payments_by_day WHERE amount_cents > 215000 ALLOW FILTERING;", None, "cql"),
    (
        "text",
        "SELECT product, count(*) FROM 'lake/capstone/marts/fct_loan.parquet' GROUP BY 1",
        None,
        "duckdb",
    ),
    ("text", "SET ch03:k 1 EX 60\nGET ch03:k\nTTL ch03:k", None, "redis"),
    (
        "text",
        "XADD ch03:payments * loan L1\nXREADGROUP GROUP loader w1 COUNT 5 STREAMS ch03:payments >",
        None,
        "redis",
    ),
    # program output and abridged statements stay copy-only
    ("text", "SET ch03:session:abc ... EX 2  ->  TTL = 2s", None, None),
    ("text", "CREATE TABLE payments_by_loan (... PRIMARY KEY ((loan_id), event_time, event_id))", None, None),
    ("text", "XADD 21 entries to ch03:payments; XGROUP CREATE loader\nworker-a read 5 entries", None, None),
    ("text", "SELECT the partition: 500 rows returned", None, None),
    ("text", "SELECT a FROM b", None, None),  # SQL, but for which database?
    ("text", "(:Person {borrower_id})-[:SUBMITTED]->(:Application {application_id})", None, None),
    ("text", "borrowers                     2000\napplications                  2393", None, None),
    ("text", "", None, None),
]


@pytest.mark.parametrize(("lang", "code", "chapter", "expected"), DETECT)
def test_console_detection(lang: str, code: str, chapter: int | None, expected: str | None) -> None:
    assert reader.detect_console(lang, code, chapter) == expected


def test_highlighting_escapes_everything() -> None:
    out = reader.highlight("SELECT '<script>' -- </code><b>\nFROM t", "sql")
    assert "<script>" not in out and "</code>" not in out and "<b>" not in out
    assert '<span class="tok-k">SELECT</span>' in out and '<span class="tok-c">' in out
    assert reader.highlight("a < b", None) == "a &lt; b"


# ---------------------------------------------------------------- through HTTP


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(TOKEN, PORT, progress=Progress(tmp_path / "progress.json"))
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def test_http_guide_endpoints(client: TestClient) -> None:
    assert client.get("/api/guide/04").status_code == 401  # the token is needed, as for every API
    meta = client.get("/api/meta", headers=H).json()
    assert [c["id"] for c in meta["guide"]] == [f"{n:02d}" for n in range(9)]
    ch = client.get("/api/guide/04", headers=H).json()
    assert (
        ch["title"] == "Wide-column with Apache Cassandra"
        and ch["toc"][0]["id"] == "the-model-in-one-paragraph"
    )
    for bad in ("99", "4", "..", "04.md", "%2e%2e"):
        assert client.get(f"/api/guide/{bad}", headers=H).status_code == 404, bad
    res = client.get("/api/search", params={"q": "tombstone"}, headers=H).json()
    assert res["results"] and res["results"][0]["chapter"] == 4


def test_http_file_viewer(client: TestClient) -> None:
    assert client.get("/api/file", params={"path": "README.md"}).status_code == 401
    ok = client.get("/api/file", params={"path": "src/nosqlde/flatten.py"}, headers=H)
    assert ok.status_code == 200 and ok.json()["kind"] == "file"
    for bad in ("../pyproject.toml", "/etc/passwd", ".git/config", "guide/../../etc/passwd", "..%2F..%2Fetc"):
        assert client.get("/api/file", params={"path": bad}, headers=H).status_code in (400, 404), bad
    assert (
        client.get("/api/file", params={"path": "src/nosqlde/studio/lessons/ch02.py"}, headers=H).status_code
        == 403
    )


def test_http_repo_images_stay_in_guide_and_docs(client: TestClient) -> None:
    ok = client.get("/repo-img/docs/img/studio-light.png")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    assert "default-src 'self'" in ok.headers["content-security-policy"]
    for bad in (
        "/repo-img/..%2F..%2Fetc%2Fpasswd",
        "/repo-img/src/nosqlde/config.py",
        "/repo-img/.git/config",
        "/repo-img/README.md",
        "/repo-img/docs/../pyproject.toml",
    ):
        assert client.get(bad).status_code == 404, bad


def test_http_reader_assets_have_the_strict_csp(client: TestClient) -> None:
    for path in (
        "/static/reader.js",
        "/static/diagrams/" + reader.diagram_files(reader.mermaid_blocks(ROOT)[0][1])["light"].name,
    ):
        res = client.get(path)
        assert res.status_code == 200, path
        csp = res.headers["content-security-policy"]
        assert "script-src 'self';" in csp and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    index = client.get("/").text
    assert 'src="/static/reader.js"' in index and "<script>" not in index and "style=" not in index


def test_abridged_or_parameterised_snippets_get_no_console() -> None:
    from nosqlde.studio.reader import detect_console

    assert detect_console("cypher", "MATCH (a:Application) RETURN a LIMIT 5") == "cypher"
    assert detect_console("cypher", "MATCH (a)\n...\nRETURN a") is None
    assert detect_console("sql", "SELECT 1\n...") is None
