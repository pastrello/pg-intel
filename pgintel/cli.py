from __future__ import annotations

import argparse
import json
import logging
import sys

from .agent import capability_report, check, collect_once, run_forever
from .capabilities import render_text
from .config import load_config
from .db import connect
from .report import text_report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pgintel", description="PG Intelligence prototype")
    p.add_argument("-c", "--config", default="/etc/pgintel/pgintel.ini")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Validate source/repository connectivity and compatibility")
    c = sub.add_parser("capabilities", help="Show PostgreSQL 13-18 capability/upgrade assessment")
    c.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of text")
    sub.add_parser("collect", help="Run one collection/analyzer cycle")
    sub.add_parser("run", help="Run the collection loop")
    r = sub.add_parser("report", help="Print a text report")
    r.add_argument("--hours", type=int, default=24)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        cfg = load_config(args.config)
        if args.command == "check":
            result = check(cfg)
            print(json.dumps(result, indent=2, default=str))
            ok = result["source"] and result["repository"]
            ok = ok and result.get("pg_stat_database_compatible") is not False
            ok = ok and result.get("pgintel_support_level") != "unsupported"
            ok = ok and result.get("expected_major_match") is not False
            if result.get("pg_stat_statements") and result.get("pg_stat_statements_compatible") is False:
                ok = False
            return 0 if ok else 2
        if args.command == "capabilities":
            result = capability_report(cfg)
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(render_text(result))
            ok = result["support"]["level"] != "unsupported" and result["support"]["expected_major_match"]
            return 0 if ok else 2
        if args.command == "collect":
            print(json.dumps(collect_once(cfg), indent=2, default=str))
            return 0
        if args.command == "run":
            run_forever(cfg)
            return 0
        if args.command == "report":
            with connect(cfg.repository.dsn) as conn:
                print(text_report(conn, cfg.instance_name, args.hours))
            return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.getLogger("pgintel").exception("Fatal error")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
