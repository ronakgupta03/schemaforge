"""Impact graph: merge DB snapshot + code facts into a semantic graph and
project the blast radius of a schema change."""
from __future__ import annotations

from collections import defaultdict

from .models import CodeFacts, DBSnapshot, ImpactEdge, ImpactGraph, ImpactNode


def _mid(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s).strip("_") or "x"


def build(snapshot: DBSnapshot, facts: CodeFacts) -> ImpactGraph:
    g = ImpactGraph(nodes={}, edges=[])

    for table in snapshot.tables.values():
        tid = f"table_{_mid(table.name)}"
        g.nodes[tid] = ImpactNode(id=tid, kind="table", label=table.name)
        for col in table.columns:
            cid = f"col_{_mid(table.name)}_{_mid(col.name)}"
            g.nodes[cid] = ImpactNode(
                id=cid, kind="column", label=f"{table.name}.{col.name}"
            )
            g.edges.append(ImpactEdge(src=tid, dst=cid, kind="has_column"))

    for m in facts.models:
        mid = f"model_{_mid(m.name)}"
        g.nodes[mid] = ImpactNode(id=mid, kind="model", label=m.name, file=m.file)
        tid = f"table_{_mid(m.table)}"
        if tid in g.nodes:
            g.edges.append(ImpactEdge(src=mid, dst=tid, kind="maps_to"))
        for c in m.columns:
            cid = f"col_{_mid(m.table)}_{_mid(c)}"
            if cid in g.nodes:
                g.edges.append(ImpactEdge(src=mid, dst=cid, kind="defines_column"))

    for a in facts.attr_accesses:
        aid = f"attr_{_mid(a.model)}_{_mid(a.column)}_{a.line}"
        g.nodes[aid] = ImpactNode(
            id=aid, kind="attr", label=f"{a.model}.{a.column}", file=a.file
        )
        mid = f"model_{_mid(a.model)}"
        if mid in g.nodes:
            g.edges.append(ImpactEdge(src=mid, dst=aid, kind="accessed_via"))

    for r in facts.raw_sql:
        rid = f"sql_{r.file.replace('/', '_').replace('.', '_')}_{r.line}"
        g.nodes[rid] = ImpactNode(
            id=rid, kind="rawsql", label=f"raw SQL @ {r.file}:{r.line}", file=r.file
        )
        for t in r.tables:
            tid = f"table_{_mid(t)}"
            if tid in g.nodes:
                g.edges.append(ImpactEdge(src=rid, dst=tid, kind="queries"))

    # per-file call map: an endpoint "executes" the attr/raw-SQL facts of any
    # function it calls (transitively) in the same file.
    calls_by_file: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for c in facts.calls:
        calls_by_file[c.file][c.caller].add(c.callee)

    def closure(func: str, file: str) -> set[str]:
        seen = {func}
        stack = [func]
        while stack:
            cur = stack.pop()
            for callee in calls_by_file.get(file, {}).get(cur, ()):
                if callee not in seen:
                    seen.add(callee)
                    stack.append(callee)
        return seen

    for e in facts.endpoints:
        eid = f"endpoint_{_mid(e.method)}_{_mid(e.path)}_{e.line}"
        g.nodes[eid] = ImpactNode(
            id=eid, kind="endpoint", label=f"{e.method} {e.path}", file=e.file
        )
        funcs = closure(e.function, e.file)
        for a in facts.attr_accesses:
            if a.file == e.file and a.function in funcs:
                aid = f"attr_{_mid(a.model)}_{_mid(a.column)}_{a.line}"
                if aid in g.nodes:
                    g.edges.append(ImpactEdge(src=eid, dst=aid, kind="executes"))
        for r in facts.raw_sql:
            if r.file == e.file and r.function in funcs:
                rid = f"sql_{r.file.replace('/', '_').replace('.', '_')}_{r.line}"
                if rid in g.nodes:
                    g.edges.append(ImpactEdge(src=eid, dst=rid, kind="executes"))

    return g


def impacted_by(g: ImpactGraph, tables: list[str]) -> dict:
    """Reverse reachability from the given table nodes.

    Returns {files, endpoints, models, columns} affected by changing those tables.
    """
    start = {f"table_{_mid(t)}" for t in tables}
    rev: dict[str, list[str]] = defaultdict(list)
    for e in g.edges:
        rev[e.dst].append(e.src)
        rev[e.src].append(e.dst)

    seen: set[str] = set()
    stack = [n for n in start if n in g.nodes]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(rev.get(n, []))

    files: set[str] = set()
    endpoints: list[str] = []
    models: list[str] = []
    columns: list[str] = []
    for nid in seen:
        node = g.nodes[nid]
        if node.kind == "model":
            models.append(node.label)
        elif node.kind == "column":
            columns.append(node.label)
        elif node.kind == "endpoint":
            endpoints.append(node.label)
        if node.file:
            files.add(node.file)
    return {
        "files": sorted(files),
        "endpoints": sorted(endpoints),
        "models": sorted(models),
        "columns": sorted(columns),
    }


def impacted_by_columns(g: ImpactGraph, columns: list[str]) -> dict:
    """Reverse reachability from column nodes — the contract gate.

    `columns` are "table.column" names. A column is SAFE to drop iff this
    returns no code sites. Code sites are model/attr/rawsql/endpoint nodes
    (NOT the column/table/schema nodes themselves, which are structural).
    """
    code_nodes: set[str] = set()

    # Map which models map to which tables
    model_to_table: dict[str, str] = {}
    for e in g.edges:
        if e.kind == "maps_to":
            model_to_table[e.src] = e.dst

    for c in columns:
        if "." in c:
            t_name, col_name = c.split(".", 1)
        else:
            t_name, col_name = "", c
        cid = f"col_{_mid(t_name)}_{_mid(col_name)}" if t_name else ""
        tid = f"table_{_mid(t_name)}" if t_name else ""

        # 1. Models defining this column
        for e in g.edges:
            if e.kind == "defines_column" and (e.dst == cid or not cid and e.dst.endswith(f"_{_mid(col_name)}")):
                code_nodes.add(e.src)

        # 2. Attr accesses on this column
        for nid, node in g.nodes.items():
            if node.kind == "attr":
                parts = node.label.split(".", 1)
                if len(parts) == 2 and parts[1] == col_name:
                    mid = f"model_{_mid(parts[0])}"
                    if not tid or model_to_table.get(mid) == tid:
                        code_nodes.add(nid)

    # 3. Transitive closures: endpoints executing attr or rawsql (reverse: dst -> src)
    rev: dict[str, list[str]] = defaultdict(list)
    for e in g.edges:
        if e.kind in ("executes",):
            rev[e.dst].append(e.src)

    seen: set[str] = set()
    stack = list(code_nodes)
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        for neighbor in rev.get(n, []):
            if neighbor in g.nodes and g.nodes[neighbor].kind in {"model", "attr", "rawsql", "endpoint"}:
                stack.append(neighbor)

    code_kinds = {"model", "attr", "rawsql", "endpoint"}
    blockers: list[dict] = []
    files: set[str] = set()
    for nid in seen:
        node = g.nodes[nid]
        if node.kind in code_kinds:
            blockers.append({"kind": node.kind, "label": node.label, "file": node.file})
            if node.file:
                files.add(node.file)
    blockers.sort(key=lambda b: (b.get("file") or "", b["label"]))
    return {
        "safe": not blockers,
        "columns": columns,
        "blockers": blockers,
        "files": sorted(files),
    }
def to_mermaid(g: ImpactGraph) -> str:
    lines = ["flowchart LR"]
    by_kind: dict[str, list[ImpactNode]] = defaultdict(list)
    for n in g.nodes.values():
        by_kind[n.kind].append(n)
    for kind in ("table", "column", "model", "attr", "rawsql", "endpoint"):
        nodes = by_kind.get(kind)
        if not nodes:
            continue
        lines.append(f"    subgraph {kind}")
        for n in sorted(nodes, key=lambda x: x.id):
            lines.append(f"        {n.id}[\"{n.label}\"]")
        lines.append("    end")
    for e in g.edges:
        lines.append(f"    {e.src} -->|{e.kind}| {e.dst}")
    return "\n".join(lines)
