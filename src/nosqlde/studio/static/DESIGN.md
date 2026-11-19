# Lesson studio: design notes

The studio's look is an original theme for "NoSQL lesson studio". It borrows ideas, not
assets, from the documentation sites of the databases the guide covers: no logos, no
brand fonts, no copied CSS. Fonts are the system's own (sans for text, a system serif for
the large page titles, a system monospace for code). Every value below is a token in
`styles.css`; the diagram colours in `tools/render_diagrams.py` (`THEMES`) use the same
values.

## What the sites do well (looked at in November 2026)

Colours were read from the live pages' computed styles in Chrome, light and dark.

| Site | What we took | Its own colours (for reference) |
| --- | --- | --- |
| MongoDB docs (mongodb.com/docs) | The base: a dark green chrome, a white reading surface and an off-white side surface, hairline borders, a quiet ink with a green cast, tabs with a coloured underline instead of a box, "On this page" on the right with a bar on the current item, callouts as a 4 px left bar with a coloured title, code blocks on a barely tinted surface with a 1 px border, a near-black green dark mode that is designed rather than inverted, blue focus rings | ink #001e2b, side #f9fbfa, borders #e8edeb / #c1c7c6, forest green #00684a, spring green #00ed64, dark page #001e2b, dark chrome #061621, note bar #016bf8 |
| Redis docs (redis.io/docs) | The Redis accent: a warm red | red #ff4438, darker #e4291e, ink #091a23 |
| Apache Cassandra docs (cassandra.apache.org/doc) | The Cassandra accent: a teal blue | #1c81a0 (header gradient #1c81a0 to #92b25e) |
| Amazon DynamoDB developer guide (docs.aws.amazon.com) | The DynamoDB accent: orange, which sits on navy | orange #ff9900 on #161d26 / #0f141a |
| Neo4j docs (neo4j.com/docs) | The Neo4j accent: a deep "baltic" blue in light, a pale teal in dark | #0a6190 light, #8fe3e8 dark, tint #e7fafb |
| DuckDB docs (duckdb.org/docs) | The DuckDB accent: a pure yellow, dark text on it | #fff100, ink #0d0d0d |

Brand colours are not used as they are where they would fail contrast: each accent below
is that brand's colour family, darkened for the light theme and lifted for the dark one,
so it reaches 3:1 on every surface it sits on.

## Palette

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--bg` | #f5f7f6 | #08120f | console side, page behind panes |
| `--surface` | #ffffff | #0e1a16 | lesson and reader panes, cards |
| `--surface-2` | #f1f4f2 | #13221d | table heads, gutters, hover |
| `--surface-3` | #e4e9e6 | #1a2d26 | tracks |
| `--border` | #dfe5e2 | #20342d | hairlines |
| `--border-strong` | #c4cdc8 | #2f4a40 | table head rule, dialogs |
| `--border-input` | #7b8983 | #678378 | buttons, inputs (3:1) |
| `--text` | #0e1d18 | #e7efeb | all body text |
| `--text-2` | #3a4a44 | #b9c7c1 | secondary text |
| `--muted` | #5a6a64 | #8fa099 | labels, meta (4.5:1) |
| `--link` | #0f5fcf | #6cb4ff | links in the reader |
| `--focus` | #1667d9 | #5aa9ff | focus ring |
| `--brand` | #0b6a4c | #00d26a | primary buttons (white / ink text) |
| `--chrome` | #0b2c22 | #050e0b | top bar, toasts |
| `--chrome-fg` / `--chrome-muted` | #f1f7f4 / #a8c3b7 | same | text on the chrome |
| `--spring` | #00e26b | same | Lesson / Read underline, toast bar |
| `--ok` / `--bad` / `--warn` / `--note` | #0b7a45 / #c62f27 / #8f5f00 / #1667d9 | #3ccf80 / #ff6f63 / #e6b34a / #5aa9ff | PASS, FAIL, hints, notes |

Database accents (`--acc-*`, and `--chrome-acc-*` on the dark top bar in both themes):

| Database | Light | Dark and on the chrome |
| --- | --- | --- |
| no database (chapters 1, 8) | #0b6a4c | #00d26a / #00e26b |
| MongoDB | #00875a | #00e26b |
| Redis | #d8392b | #ff6a5c |
| Cassandra | #1c7f9e | #4cb8da |
| DynamoDB | #bb6400 | #ff9a1f |
| Neo4j | #0a6190 | #7fd8e0 |
| DuckDB (and the capstone) | #877a00 | #f5e51b |

A class (`acc-mongo`, `acc-redis`, `acc-cql`, `acc-dynamodb`, `acc-cypher`,
`acc-duckdb`, `acc-none`) sets `--acc` for everything inside it. The accent marks UI
parts only: console tab underline and dot, the current chapter's underline and progress
ring in the top bar, the lesson header band and stripe, the progress bar, the current
step pill, exercise bars, tags, the quiz's chosen answer, the reader's progress bar and
current contents item, status-bar dots, code-block top rules. Text is always ink.

Contrast is checked by a script against the tokens in `styles.css`: body text, labels
and syntax colours reach 4.5:1 on every surface they use (lowest: 4.70 light, 5.37
dark); accents, focus rings, input borders and status colours reach 3:1 (lowest: 3.30
light, 4.00 dark). The accents are told apart by the database name that is always next
to them, never by colour alone: Redis red and DynamoDB orange, and Cassandra's and
Neo4j's blues, are close by design because the brands are.

## Type

System sans for text (`ui-sans-serif, system-ui, ...`), a system serif for page titles
only (`ui-serif, "Iowan Old Style", Palatino, Georgia, serif`), system monospace for
code. Weights: 400 text, 550 to 650 for UI labels and headings.

| Role | Size / line height |
| --- | --- |
| Reader body | 16.5 px / 1.7, 68 characters wide |
| Lesson body | 15 px / 1.55 to 1.65 |
| Page title (serif) | 28 to 34 px lesson, 32 to 42 px reader / 1.12 to 1.15 |
| h2 | 21 to 24 px, 650 |
| h3 | 16 to 18 px, 650 |
| Labels ("Run this", "Exercise 2.5") | 11.5 to 12 px, 700, uppercase, 0.06 to 0.08 em |
| Code | 12.5 to 13 px / 1.55 to 1.6 |

## Spacing and shape

A 4 px grid: 4, 6, 8, 10, 12, 14, 16, 18, 24, 32, 56. Radius 6 px for buttons and
inputs, 10 px for code blocks, results and tables, 12 px for cards and dialogs, pills
fully round. Shadows are low and green-tinted in light, plain black in dark. The top bar
is 56 px, the status bar 32 px.

## Components

- **Top bar**: the chrome. Lesson / Read and the chapters are tabs with a 3 px underline
  flush with the bar's lower edge (spring green for the mode, the chapter's accent for
  the chapter), a progress ring per chapter, search as a field-like button.
- **Lesson header**: a full-width band tinted with the chapter's accent, a 3 px stripe on
  top, a serif title, the actions, the progress bar.
- **Steps**: pills; the current one is outlined in the accent; a finished step's number
  becomes a check on an accent disc.
- **Run this**: a card with a database tag, Load and Run this, the code on the code
  surface.
- **Exercises**: cards with a 4 px accent bar, an uppercase number, a state pill
  (passed in green with a check), hints as amber-barred notes, PASS / FAIL panels with a
  solid badge, a tinted head and Expected / Got side by side (stacked when the card is
  narrow).
- **Console**: underline tabs, an accent-barred "working on" strip, the editor with a
  gutter, a toolbar with the primary Run button, results as cards with a segmented
  Table / JSON switch, sticky uppercase table heads, a JSON tree with chevrons.
- **Reader**: "On this page" on the right with an accent bar on the current section,
  code blocks with an uppercase language label and Copy / Open in console, lab output
  on a second surface with a dashed rule, tables with a stronger head rule, blockquotes
  as note callouts, diagrams in a bordered figure.
- **Search**: a dropdown dialog with a large field, results with a chapter pill in that
  chapter's accent and highlighted terms.
- **Status bar**: one chip per database; a filled accent dot when up, a hollow red ring,
  a red tint and the `make` command when down.
- **Toast**: the chrome colour with a spring green bar.
