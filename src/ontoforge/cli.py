"""``python -m ontoforge`` — compile an R2RML mapping to SQL."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ontoforge.compiler import CompileError, compile_mapping
from ontoforge.compiler.identifiers import IdentifierError
from ontoforge.dialects import DatabricksDialect, SQLiteDialect
from ontoforge.r2rml import MappingError, parse_r2rml

DIALECTS = {"databricks": DatabricksDialect, "sqlite": SQLiteDialect}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ontoforge")
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("compile", help="compile an R2RML mapping (Turtle) to a triple-producing SQL statement")
    c.add_argument("mapping", type=Path)
    c.add_argument("--dialect", choices=sorted(DIALECTS), default="databricks")
    target = c.add_mutually_exclusive_group()
    target.add_argument("--view", metavar="NAME", help="wrap the query in CREATE OR REPLACE VIEW NAME")
    target.add_argument("--table", metavar="NAME", help="wrap the query in CREATE OR REPLACE TABLE NAME AS")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        compiled = compile_mapping(parse_r2rml(args.mapping.read_text()), DIALECTS[args.dialect]())
        if args.view:
            out = compiled.view_ddl(args.view)
        elif args.table:
            out = compiled.table_ddl(args.table)
        else:
            out = compiled.sql
    except (MappingError, CompileError, IdentifierError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(out)
    return 0
