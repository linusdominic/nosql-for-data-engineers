"""Command line entry point: `uv run nosqlde <command>`.

nosqlde datagen                 print the synthetic data summary
nosqlde lab 02                  run chapter 2's lab
nosqlde check 02 [--solutions]  check your exercise answers for chapter 2
nosqlde capstone [--scale N]    run the end-to-end capstone pipeline
nosqlde studio [--port 8790]    the lesson studio: lessons and live consoles in a browser
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time

from nosqlde.clients import ServiceUnavailable

CHAPTERS = {
    "01": "ch01_foundations",
    "02": "ch02_mongodb",
    "03": "ch03_redis",
    "04": "ch04_cassandra",
    "05": "ch05_dynamodb",
    "06": "ch06_neo4j",
    "07": "ch07_capstone",
    "08": "ch08_choosing",
}
LABS = {"02", "03", "04", "05", "06"}


def _chapter(value: str) -> str:
    key = value.zfill(2)
    if key not in CHAPTERS:
        raise argparse.ArgumentTypeError(f"unknown chapter {value!r}; use one of {sorted(CHAPTERS)}")
    return key


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nosqlde", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("datagen", help="print the synthetic data summary")
    lab = sub.add_parser("lab", help="run a chapter's lab")
    lab.add_argument("chapter", type=_chapter)
    check = sub.add_parser("check", help="check a chapter's exercises")
    check.add_argument("chapter", type=_chapter)
    check.add_argument("--solutions", action="store_true", help="check solutions/ instead")
    cap = sub.add_parser("capstone", help="run the end-to-end capstone")
    cap.add_argument("--scale", type=int, default=2_000, help="number of borrowers (default 2000)")
    studio = sub.add_parser("studio", help="start the lesson studio on 127.0.0.1")
    studio.add_argument("--port", type=int, default=8790, help="port on 127.0.0.1 (default 8790)")
    args = parser.parse_args(argv)

    start = time.perf_counter()
    try:
        if args.command == "datagen":
            from nosqlde import datagen

            for key, value in datagen.summary(datagen.generate()).items():
                print(f"{key:<26} {value:>7}")
            return 0
        if args.command == "lab":
            if args.chapter not in LABS:
                print(
                    f"Chapter {args.chapter} has no database lab; read the guide and run "
                    f"`make check-{args.chapter}`."
                )
                return 0
            module = importlib.import_module(f"nosqlde.labs.{CHAPTERS[args.chapter]}")
            module.run()
            print(f"\nlab {args.chapter} finished in {time.perf_counter() - start:.1f}s")
            return 0
        if args.command == "check":
            module = importlib.import_module(f"nosqlde.checks.{CHAPTERS[args.chapter]}")
            code: int = module.run(solutions=args.solutions)
            print(f"check {args.chapter} finished in {time.perf_counter() - start:.1f}s")
            return code
        if args.command == "capstone":
            from nosqlde.capstone import pipeline

            return pipeline.main(scale=args.scale)
        if args.command == "studio":
            from nosqlde.studio import server

            return server.serve(port=args.port)
    except ServiceUnavailable as err:
        print(f"\nERROR: {err}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
