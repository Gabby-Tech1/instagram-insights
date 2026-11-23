"""Instagram Insights - pull posts, analyse performance, recommend content.

    python main.py run                      # full pipeline on sample data
    python main.py run --source instagram   # full pipeline on your real account
    python main.py fetch --source instagram # only pull + store posts
    python main.py analyse                  # analyse + recommend from stored posts
"""
import argparse
import json
import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=".*OpenSSL.*")  # macOS system Python + urllib3 noise

from dotenv import load_dotenv

from insights.analytics import analyse
from insights.intelligence import recommend
from insights.report import render_markdown
from insights.sources import get_source
from insights.store import Store

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("insights")


def cmd_fetch(args) -> None:
    posts = get_source(args.source).fetch_posts(limit=args.limit)
    n = Store(args.db).upsert(posts)
    log.info("Stored %d posts from %s in %s", n, args.source, args.db)


def cmd_analyse(args) -> None:
    posts = Store(args.db).all_posts()
    if not posts:
        raise SystemExit("No posts stored yet - run `python main.py fetch` first")
    log.info("Analysing %d posts", len(posts))
    stats = analyse(posts)
    log.info("Generating recommendations")
    recs = recommend(stats, account_context=args.context, use_llm=not args.no_llm)

    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / "report.json").write_text(json.dumps({"stats": stats, "recommendations": recs}, indent=2, default=str))
    (out / "report.md").write_text(render_markdown(stats, recs))
    log.info("Engine: %s", recs["engine"])
    log.info("Wrote %s and %s", out / "report.md", out / "report.json")

    print("\n" + recs["summary"] + "\n")
    for i, r in enumerate(recs["recommendations"], 1):
        print(f"{i}. [{r['priority']}] {r['title']} - {r['format']}, {r['best_day']} {r['best_time']}")
        print(f"   evidence: {r['evidence']}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default="insights.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_fetch_args(sp):
        sp.add_argument("--source", choices=["mock", "instagram"], default="mock")
        sp.add_argument("--limit", type=int, default=100)

    def add_analyse_args(sp):
        sp.add_argument("--context", default="", help='e.g. "Specialty coffee roaster, sells online, goal: grow sales"')
        sp.add_argument("--no-llm", action="store_true", help="use rule-based recommendations only")
        sp.add_argument("--out", default="output")

    f = sub.add_parser("fetch", help="pull posts from a source and store them")
    add_fetch_args(f)
    a = sub.add_parser("analyse", help="analyse stored posts and generate recommendations")
    add_analyse_args(a)
    r = sub.add_parser("run", help="fetch + analyse in one go")
    add_fetch_args(r)
    add_analyse_args(r)

    args = p.parse_args()
    if args.cmd in ("fetch", "run"):
        cmd_fetch(args)
    if args.cmd in ("analyse", "run"):
        cmd_analyse(args)


if __name__ == "__main__":
    main()
