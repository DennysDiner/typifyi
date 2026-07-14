"""Command-line entry points.

  python -m tasmon run --schedule tier1     # fetch + score + alerts (twice daily)
  python -m tasmon run --schedule tier2     # paywalled headlines (daily)
  python -m tasmon run --schedule tier3     # weekly sweep
  python -m tasmon digest                   # build today's digest (+ email if configured)
  python -m tasmon health                   # source health to terminal
  python -m tasmon test-email               # verify SMTP settings
"""

import argparse
import os
import sys

from tasmon import db
from tasmon.config import Config


def main(argv=None):
    parser = argparse.ArgumentParser(prog="tasmon")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="fetch sources, score, fire alerts")
    p_run.add_argument("--schedule", choices=["tier1", "tier2", "tier3"],
                       required=True)
    p_run.add_argument("--source", help="run a single source id (for testing)")

    p_digest = sub.add_parser("digest", help="build daily digest")
    p_digest.add_argument("--date", help="YYYY-MM-DD (default: today)")
    p_digest.add_argument("--no-email", action="store_true",
                          help="skip emailing even if digest.email is true")

    sub.add_parser("health", help="print source health")
    sub.add_parser("test-email", help="send a test email using config settings")
    sub.add_parser("init", help="create the database")

    args = parser.parse_args(argv)
    cfg = Config.load(args.config)
    os.makedirs(os.path.dirname(cfg.db_path) or ".", exist_ok=True)
    conn = db.connect(cfg.db_path)

    if args.command == "init":
        print(f"Database ready at {cfg.db_path}")

    elif args.command == "run":
        from tasmon.alerts import AlertEngine
        from tasmon.ingest import Ingestor
        from tasmon.summarize import summarize_new_items

        ingestor = Ingestor(cfg, conn)
        if args.source:
            matches = [s for s in cfg.sources if s["id"] == args.source]
            if not matches:
                sys.exit(f"no source with id {args.source!r}")
            ingestor.run_source(matches[0])
        else:
            ingestor.run_schedule(args.schedule)
        new = ingestor.new_items
        print(f"{len(new)} new item(s).")

        fired = AlertEngine(cfg, conn).check_items(new)
        if fired:
            print(f"{len(fired)} alert(s) fired.")
        n = summarize_new_items(cfg, conn)
        if n:
            print(f"{n} item(s) summarised.")

    elif args.command == "digest":
        from tasmon.digest import build_digest
        markdown, path = build_digest(cfg, conn, args.date)
        print(markdown)
        print(f"\n[written to {path}]")
        if cfg.digest_email_enabled and not args.no_email:
            from tasmon.alerts import send_email
            try:
                send_email(cfg, f"Tasmania monitor digest — {os.path.basename(path)[:-3]}",
                           markdown)
                print("[digest emailed]")
            except Exception as e:  # noqa: BLE001
                print(f"!! digest email failed: {e}")

    elif args.command == "health":
        from tasmon.digest import source_health_section
        print("\n".join(source_health_section(cfg, conn)))

    elif args.command == "test-email":
        from tasmon.alerts import send_email
        send_email(cfg, "tasmon test email",
                   "If you can read this, tasmon's SMTP settings work.")
        print("Test email sent.")

    conn.close()


if __name__ == "__main__":
    main()
