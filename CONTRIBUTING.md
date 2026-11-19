# Contributing

Corrections and improvements are welcome, especially:

- a statement that is wrong, or true only for some versions (say which version and link
  the official documentation);
- a lab step whose output on your machine differs from the guide (include your OS,
  CPU architecture and Docker version);
- clearer explanations for someone who knows SQL but not NoSQL.

## Ground rules for the content

- **Every number comes from a run.** Row counts, timings, `explain` output and query
  results in the guide are copied from a real run of the code in this repository. If you
  change a lab, re-run it and update the quoted output; do not edit numbers by hand.
- **Say what is not verified.** Each chapter ends with a "What is not verified" list.
  If you add a claim you could not demonstrate, add it there.
- **Version-specific behaviour names its version** and links the documentation for that
  version.
- **All data is fictional.** Extend `src/nosqlde/datagen.py` rather than adding real
  names, companies, addresses or numbers. Phone numbers use the unassigned `+999` prefix
  and emails use `example.com`.
- **Write your own explanations.** Link to official documentation instead of copying it.

## Development

```bash
make setup                     # uv sync --python 3.12
make test                      # unit tests, no database needed
make lint                      # ruff check, ruff format --check, mypy --strict
make up-capstone up-03 up-05   # every database
make test-integration          # every lab, every check against solutions/, the capstone,
                               # and every studio exercise (solution passes, wrong answers fail)
make studio                    # the lesson studio on 127.0.0.1:8790
make diagrams                  # after editing a mermaid diagram in guide/ (needs Chrome)
make down
```

The generator's output is pinned by `tests/unit/test_datagen.py::EXPECTED_SUMMARY`.
If you change the generator on purpose, update that test and every number the guide
quotes from the affected labs.

When you change an exercise, change the matching file in `solutions/` and the check in
`src/nosqlde/checks/`, and confirm that `make check-NN` fails cleanly on the untouched
starter file and passes with `SOLUTIONS=1`.

When you add or change a studio exercise (`src/nosqlde/studio/lessons/chNN.py`), give it
a reference solution, one to three hints and at least one plausible wrong answer;
`make test-integration` then checks that the solution passes and that every wrong answer,
and a statement that does nothing, fails. Studio data comes from the lab's own loading
code in `prepare.py`, so the numbers stay those of the guide.

The studio's reader renders `guide/*.md` as it is, so a guide edit shows on the next page
load. A link to another chapter (`03-key-value-redis.md#streams`) or to a repository
file (`../src/nosqlde/flatten.py`) becomes a link inside the studio, and
`tests/unit/test_studio_reader.py` fails on a link or anchor that leads nowhere. A
mermaid diagram is shown from SVGs that `make diagrams` writes; the same test fails
until they exist for the edited diagram.

## Pull requests

Keep them small and focused. Describe what you ran to verify the change (for example
`make lab-04 && make check-04 SOLUTIONS=1`) and paste the relevant output.
