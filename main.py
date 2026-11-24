"""Instagram Content Intelligence System - command line.

    python main.py run                                  # full pipeline on sample data
    python main.py run --source instagram               # full pipeline on your real account
    python main.py run --source csv --path posts.csv    # full pipeline on a CSV export
    python main.py fetch --source instagram             # only pull + store posts
    python main.py analyse                              # analyse + recommend from stored posts
"""
import argparse
import json
import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=".*OpenSSL.*")  # macOS system Python + urllib3 noise
warnings.filterwarnings("ignore", message="Mean of empty slice")

from dotenv import load_dotenv

from insights import pipeline
from insights.report import render_markdown
from insights.store import Store

load_dotenv(Path(__file__).resolve().parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("insights")


def cmd_fetch(args, store: Store) -> None:
    kwargs = {"path": args.path} if args.path else {}
    n = pipeline.collect(store, args.source, limit=args.limit, **kwargs)
    log.info("Stored %d posts from %s in %s", n, args.source, args.db)


def cmd_analyse(args, store: Store) -> None:
    try:
        result = pipeline.run(store, context=args.context, use_llm=not args.no_llm)
    except LookupError as e:
        raise SystemExit(str(e))
    stats, recs = result["stats"], result["recommendations"]

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / "report.json").write_text(json.dumps(result, indent=2, default=str))
    (out / "report.md").write_text(render_markdown(stats, recs))
    g = recs["grounding_summary"]
    log.info("Tagging: %s | Recommendations: %s | Verified against data: %d/%d",
             stats["overview"]["tagger"], recs["engine"], g["verified"], g["total"])
    log.info("Wrote %s and %s", out / "report.md", out / "report.json")

    print("\n" + recs["summary"] + "\n")
    for i, r in enumerate(recs["recommendations"], 1):
        mark = "verified" if r["grounding"]["grounded"] else "NOT verified"
        print(f"{i}. [{r['priority']}] {r['title']} - {r['format']}, {r['best_day']} {r['best_time']} ({mark})")
        print(f"   evidence: {r['evidence']}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="insights.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_fetch_args(sp):
        sp.add_argument("--source", choices=["mock", "instagram", "csv"], default="mock")
        sp.add_argument("--path", help="file path for --source csv (or a custom JSON for mock)")
        sp.add_argument("--limit", type=int, default=100)

    def add_analyse_args(sp):
        sp.add_argument("--context", default="", help='e.g. "Specialty coffee roaster, sells online, goal: grow sales"')
        sp.add_argument("--no-llm", action="store_true", help="rule-based tagging and recommendations only")
        sp.add_argument("--out", default="output")

    f = sub.add_parser("fetch", help="pull posts from a source and store them")
    add_fetch_args(f)
    a = sub.add_parser("analyse", help="analyse stored posts and generate recommendations")
    add_analyse_args(a)
    r = sub.add_parser("run", help="fetch + analyse in one go")
    add_fetch_args(r)
    add_analyse_args(r)

    args = p.parse_args()
    store = Store(args.db)
    if args.cmd in ("fetch", "run"):
        cmd_fetch(args, store)
    if args.cmd in ("analyse", "run"):
        cmd_analyse(args, store)


if __name__ == "__main__":
    main()
