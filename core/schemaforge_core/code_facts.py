"""Deterministic code facts from a Python source tree.

Pass 1 collects SQLAlchemy declarative models (class ↔ table ↔ columns).
Pass 2, with the model map known, collects FastAPI endpoints, attribute
accesses of known model columns on model-typed arguments, and raw-SQL table
references (via sqlparse). No LLM involved; outputs are stable JSON.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import sqlparse
from sqlparse import tokens as T

from .models import AttrAccess, CodeFacts, EndpointFact, FunctionCall, ModelFact, RawSqlRef

_ROUTE_METHODS = {"get", "post", "put", "patch", "delete"}
_TABLE_KEYWORDS = {"FROM", "JOIN", "INTO", "UPDATE", "TABLE"}


def _tables_from_sql(sql: str) -> list[str]:
    """Table names following FROM/JOIN/INTO/UPDATE/TABLE in a SQL string."""
    try:
        parsed = sqlparse.parse(sql)
    except Exception:
        return []
    if not parsed:
        return []
    found: list[str] = []
    for stmt in parsed:
        prev_keyword: ast.expr | None = None
        for tok in stmt.flatten():
            if tok.is_whitespace:
                continue
            if (
                tok.ttype in (T.Keyword, T.Keyword.DML) or tok.ttype is None
            ) and tok.value.upper() in _TABLE_KEYWORDS:
                prev_keyword = tok
                continue
            if prev_keyword is not None:
                if tok.ttype is T.Name or tok.ttype is None:
                    v = tok.value.strip().strip('"').strip("`")
                    if v and not v.startswith("("):
                        found.append(v)
                    prev_keyword = None
                elif tok.ttype in (T.Punctuation, T.Operator):
                    prev_keyword = None
    seen: set[str] = set()
    out: list[str] = []
    for t in found:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _fid(path: str) -> str:
    return hashlib.md5(path.encode()).hexdigest()[:8]


def _model_names_in_annotation(ann: ast.expr, models: set[str]) -> list[str]:
    names: list[str] = []
    for n in ast.walk(ann):
        if isinstance(n, ast.Name) and n.id in models:
            names.append(n.id)
    return list(dict.fromkeys(names))


class _ModelPass(ast.NodeVisitor):
    """Pass 1: SQLAlchemy declarative models."""

    def __init__(self, path: Path):
        self.path = path
        self.models: list[ModelFact] = []
        self.columns_by_model: dict[str, list[str]] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        table: str | None = None
        columns: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Name) and t.id == "__tablename__":
                        if (
                            isinstance(stmt.value, ast.Constant)
                            and isinstance(stmt.value.value, str)
                        ):
                            table = stmt.value.value
                if isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name):
                    if stmt.value.func.id in ("mapped_column", "Column"):
                        for t in stmt.targets:
                            if isinstance(t, ast.Name):
                                columns.append(t.id)
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                if isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name):
                    if stmt.value.func.id in ("mapped_column", "Column"):
                        columns.append(stmt.target.id)
        if table:
            self.models.append(
                ModelFact(
                    name=node.name, table=table, columns=columns,
                    file=str(self.path), line=node.lineno,
                )
            )
            self.columns_by_model[node.name] = columns
        self.generic_visit(node)


class _BodyVisitor(ast.NodeVisitor):
    """Records attr accesses / raw SQL inside ONE function body.

    Skips nested FunctionDef/Lambda/ClassDef (handled separately by the main
    visitor) so arg-type maps don't leak across scopes.
    """

    def __init__(self, owner: "_FunctionPass", arg_models: dict[str, str]):
        self.owner = owner
        self.arg_models = arg_models

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in self.arg_models
            and node.attr in self.owner.columns_by_model.get(self.arg_models[node.value.id], [])
        ):
            self.owner.attr_accesses.append(
                AttrAccess(
                    model=self.arg_models[node.value.id],
                    column=node.attr,
                    file=str(self.owner.path),
                    line=node.lineno,
                    function=self.owner.func_name,
                )
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in self.owner.defined:
            self.owner.calls.append(
                FunctionCall(
                    caller=self.owner.func_name or "",
                    callee=node.func.id,
                    file=str(self.owner.path),
                    line=node.lineno,
                )
            )
        is_text = isinstance(node.func, ast.Name) and node.func.id == "text"
        is_execute = (
            isinstance(node.func, ast.Attribute) and node.func.attr == "execute"
        )
        if (is_text or is_execute) and node.args and isinstance(
            node.args[0], ast.Constant
        ) and isinstance(node.args[0].value, str):
            tables = _tables_from_sql(node.args[0].value)
            if tables:
                self.owner.raw_sql.append(
                    RawSqlRef(
                        tables=tables,
                        file=str(self.owner.path),
                        line=node.lineno,
                        function=self.owner.func_name,
                    )
                )
        self.generic_visit(node)


class _FunctionPass(ast.NodeVisitor):
    """Pass 2: endpoints, attr accesses, raw SQL (needs the model map)."""

    def __init__(
        self,
        path: Path,
        columns_by_model: dict[str, list[str]],
        router_prefixes: dict[str, str] | None = None,
        defined: set[str] | None = None,
    ):
        self.path = path
        self.columns_by_model = columns_by_model
        self.router_prefixes = router_prefixes or {}
        self.defined = defined or set()
        self.endpoints: list[EndpointFact] = []
        self.attr_accesses: list[AttrAccess] = []
        self.raw_sql: list[RawSqlRef] = []
        self.calls: list[FunctionCall] = []
        self.func_name: str | None = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function(node)

    def _handle_function(self, node) -> None:
        outer = self.func_name
        self.func_name = node.name

        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr in _ROUTE_METHODS
                and dec.args
                and isinstance(dec.args[0], ast.Constant)
                and isinstance(dec.args[0].value, str)
            ):
                var_name = dec.func.value.id if isinstance(dec.func.value, ast.Name) else ""
                prefix = self.router_prefixes.get(var_name, "")
                raw_path = dec.args[0].value
                if prefix:
                    if raw_path and not raw_path.startswith("/"):
                        endpoint_path = f"{prefix}/{raw_path}"
                    else:
                        endpoint_path = f"{prefix}{raw_path}"
                else:
                    endpoint_path = raw_path

                self.endpoints.append(
                    EndpointFact(
                        path=endpoint_path,
                        method=dec.func.attr.upper(),
                        file=str(self.path),
                        line=node.lineno,
                        function=node.name,
                    )
                )

        arg_models: dict[str, str] = {}
        for a in list(node.args.posonlyargs) + list(node.args.args):
            if a.annotation is not None:
                names = _model_names_in_annotation(
                    a.annotation, set(self.columns_by_model)
                )
                if len(names) == 1:
                    arg_models[a.arg] = names[0]

        bv = _BodyVisitor(self, arg_models)
        for stmt in node.body:
            bv.visit(stmt)

        for dec in node.decorator_list:
            self.visit(dec)
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.visit(stmt)

        self.func_name = outer


def _extract_router_prefixes(tree: ast.AST) -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and isinstance(node.value, ast.Call):
                    func_name = ""
                    if isinstance(node.value.func, ast.Name):
                        func_name = node.value.func.id
                    elif isinstance(node.value.func, ast.Attribute):
                        func_name = node.value.func.attr
                    if func_name == "APIRouter":
                        prefix = ""
                        for kw in node.value.keywords:
                            if (
                                kw.arg == "prefix"
                                and isinstance(kw.value, ast.Constant)
                                and isinstance(kw.value.value, str)
                            ):
                                prefix = kw.value.value
                        if (
                            not prefix
                            and node.value.args
                            and isinstance(node.value.args[0], ast.Constant)
                            and isinstance(node.value.args[0].value, str)
                        ):
                            prefix = node.value.args[0].value
                        prefixes[t.id] = prefix
    return prefixes


def collect_facts(app_dir: str) -> CodeFacts:
    root = Path(app_dir)
    facts = CodeFacts()
    columns_by_model: dict[str, list[str]] = {}
    py_files = sorted(p for p in root.rglob("*.py") if "tests" not in p.parts)
    for f in py_files:
        try:
            tree = ast.parse(f.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        mp = _ModelPass(f)
        mp.visit(tree)
        facts.models.extend(mp.models)
        columns_by_model.update(mp.columns_by_model)
    for f in py_files:
        try:
            tree = ast.parse(f.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        router_prefixes = _extract_router_prefixes(tree)
        defined = {
            n.name
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        fp = _FunctionPass(f, columns_by_model, router_prefixes, defined=defined)
        fp.visit(tree)
        facts.endpoints.extend(fp.endpoints)
        facts.attr_accesses.extend(fp.attr_accesses)
        facts.raw_sql.extend(fp.raw_sql)
        facts.calls.extend(fp.calls)
    return facts
