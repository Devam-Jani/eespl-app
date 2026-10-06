"""Clean up the T&C clause library.

    docker compose exec api python -m app.cli.clean_tc --dry-run   # summary only, no changes
    docker compose exec api python -m app.cli.clean_tc             # apply

Merges near-duplicates, hides rows that are not clauses / client checklist answers /
project-specific text, flags clauses that lost a leading number on import, and makes sure no
template holds a hidden or merged clause. Safe to run again: the second run changes nothing,
and decisions made by a person in the app are never overridden. See app.masters.tc.
"""

import argparse

from app import audit
from app.db import SessionLocal
from app.masters.tc import CleanupSummary, clean_tc


def _table(rows: list[tuple[str, object]]) -> str:
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"  {label:<{width}}  {value:>5}" for label, value in rows)


def print_summary(s: CleanupSummary, dry_run: bool) -> None:
    print("T&C cleanup" + (" (dry run, nothing saved)" if dry_run else ""))
    print(_table([
        ("duplicate groups merged", s.groups_merged),
        ("clauses merged into a master", s.clauses_merged),
        ("hidden: not_a_clause", s.hidden["not_a_clause"]),
        ("hidden: client_checklist", s.hidden["client_checklist"]),
        ("hidden: project_specific", s.hidden["project_specific"]),
        ("flagged needs_review", s.flagged),
    ]))  # fmt: skip
    print("Active clauses per category:")
    print(_table(sorted(s.active_per_category.items())))
    print(f"  {'total':<{max(len(k) for k in s.active_per_category)}}  "
          f"{sum(s.active_per_category.values()):>5}")  # fmt: skip
    print("Templates (clause count):")
    print(_table(sorted(s.templates.items())))
    if s.merged_groups:
        print("Merged groups (master  <=  variants):")
        for master, variants in s.merged_groups:
            print(f"  {master[:90]}")
            for v in variants:
                print(f"      <= {v[:90]}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli.clean_tc")
    parser.add_argument("--dry-run", action="store_true", help="print the summary, save nothing")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        summary = clean_tc(db)
        if args.dry_run:
            db.rollback()
        else:
            audit.record(
                db,
                "tc.cleanup",
                "tc_clause",
                None,
                after={
                    "groups_merged": summary.groups_merged,
                    "clauses_merged": summary.clauses_merged,
                    "hidden": summary.hidden,
                    "flagged": summary.flagged,
                },
            )
            db.commit()
    print_summary(summary, args.dry_run)


if __name__ == "__main__":
    main()
