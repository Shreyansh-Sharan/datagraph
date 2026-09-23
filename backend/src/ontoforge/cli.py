"""``ontoforge`` / ``python -m ontoforge`` command line."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ontoforge.compiler import CompileError, compile_mapping
from ontoforge.compiler.identifiers import IdentifierError
from ontoforge.config import load_settings
from ontoforge.dialects import DIALECTS
from ontoforge.r2rml import MappingError, parse_r2rml


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ontoforge", description="Semantic layer / knowledge-graph backend")
    sub = ap.add_subparsers(dest="command", required=True)

    c = sub.add_parser("compile", help="compile an R2RML mapping (Turtle) to a triple-producing SQL statement")
    c.add_argument("mapping", type=Path)
    c.add_argument("--dialect", choices=sorted(DIALECTS), default="databricks")
    target = c.add_mutually_exclusive_group()
    target.add_argument("--view", metavar="NAME", help="wrap the query in CREATE OR REPLACE VIEW NAME")
    target.add_argument("--table", metavar="NAME", help="wrap the query in CREATE OR REPLACE TABLE NAME AS")

    for name, help_ in (("migrate", "apply database migrations"), ("serve", "run the REST API (uvicorn)"),
                        ("serve-mcp", "run the MCP server over stdio")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--database-url", default=None, help="overrides ONTOFORGE_DATABASE_URL")
        p.add_argument("--schema", default=None, help="Postgres schema (overrides ONTOFORGE_DATABASE_SCHEMA)")
        if name == "serve":
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", type=int, default=8000)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {"compile": _compile, "migrate": _migrate, "serve": _serve, "serve-mcp": _serve_mcp}[args.command](args)
    except (MappingError, CompileError, IdentifierError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _compile(args) -> int:
    compiled = compile_mapping(parse_r2rml(args.mapping.read_text()), DIALECTS[args.dialect]())
    print(compiled.view_ddl(args.view) if args.view else compiled.table_ddl(args.table) if args.table else compiled.sql)
    return 0


def _database(args):
    from ontoforge.db import Database
    settings = load_settings()
    return Database(args.database_url or settings.database_url, schema=args.schema or settings.database_schema)


def _migrate(args) -> int:
    from ontoforge.db import run_migrations
    db = _database(args)
    try:
        applied = run_migrations(db)
        print("\n".join(f"applied {name}" for name in applied) if applied else "up to date")
    finally:
        db.close()
    return 0


def _serve(args) -> int:
    import uvicorn
    from ontoforge.api import create_app
    from ontoforge.db import run_migrations
    db = _database(args)
    run_migrations(db)
    uvicorn.run(create_app(db), host=args.host, port=args.port)
    return 0


def _serve_mcp(args) -> int:
    from ontoforge.api.app import stdio_mcp_server
    stdio_mcp_server(_database(args)).run(transport="stdio")
    return 0
