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
    found_cols: set[str] = set()   # columns that exist in the graph at all
    absent_cols: list[str] = []    # requested columns absent (typo/stale snapshot)

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

        # A column is "present" if it appears as a column node, a
        # defines_column edge, or an attr access. An absent requested column
        # (typo, stale DB snapshot, wrong table) cannot be proven safe — it
        # must BLOCK the gate rather than silently pass as SAFE.
        present = False
        if cid and cid in g.nodes:
            present = True

        # 1. Models defining this column
        for e in g.edges:
            if e.kind == "defines_column" and (e.dst == cid or not cid and e.dst.endswith(f"_{_mid(col_name)}")):
                code_nodes.add(e.src)
                present = True

        # 2. Attr accesses on this column
        for nid, node in g.nodes.items():
            if node.kind == "attr":
                parts = node.label.split(".", 1)
                if len(parts) == 2 and parts[1] == col_name:
                    mid = f"model_{_mid(parts[0])}"
                    if not tid or model_to_table.get(mid) == tid:
                        code_nodes.add(nid)
                        present = True

        if not present:
            absent_cols.append(c)
            found_cols.discard(c)
        else:
            found_cols.add(c)
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
    # An absent requested column (not in the DB snapshot / code graph) is a
    # hard BLOCKER — the gate cannot prove a column it cannot see is safe.
    for c in absent_cols:
        blockers.append({"kind": "absent", "label": c, "file": ""})
    blockers.sort(key=lambda b: (b.get("file") or "", b["label"]))
    return {
        "safe": not blockers,
        "columns": columns,
        "blockers": blockers,
        "files": sorted(files),
        "absent": absent_cols,
    }
def to_mermaid(g: ImpactGraph) -> str:
    """Bounded display projection: tables, models, endpoint route groups.

    Column nodes and individual endpoint nodes are dropped from the
    rendered graph (they dominate node counts on real schemas and still
    live in graph.json). Endpoints are aggregated by API route prefix
    (e.g. ``api/auth — 12 endpoints``) and edges are collapsed and
    deduplicated: group -> table (via raw SQL) and group -> model (via
    attr access, only when the group has no table edge). The result stays
    small enough to render in the Impact tab before the approval gate.
    """
    keep = {"table", "model", "endpoint"}
    kept = {nid for nid, n in g.nodes.items() if n.kind in keep}
    endpoints = {nid for nid in kept if g.nodes[nid].kind == "endpoint"}

    def endpoint_group(label: str) -> str:
        # "GET /api/auth/check-email/:email" -> "api/auth"
        parts = label.split()
        path = parts[-1] if parts else label
        segs = [s for s in path.split("/") if s]
        if not segs:
            return label
        return "/".join(segs[:2])

    # Collapse endpoint reachability: endpoint -> table (via raw SQL) and
    # endpoint -> model (via attr).
    attr_model: dict[str, str] = {}
    rawsql_tables: dict[str, set[str]] = defaultdict(set)
    for e in g.edges:
        if e.kind == "accessed_via" and e.src in kept:
            attr_model[e.dst] = e.src
        elif e.kind == "queries" and e.dst in kept:
            rawsql_tables[e.src].add(e.dst)

    groups: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"tables": set(), "models": set()})
    endpoint_table: dict[str, set[str]] = defaultdict(set)
    for e in g.edges:
        if e.kind != "executes" or e.src not in endpoints:
            continue
        dst = g.nodes.get(e.dst)
        if dst is None:
            continue
        group = endpoint_group(g.nodes[e.src].label)
        if dst.kind == "attr":
            model = attr_model.get(e.dst)
            if model is not None:
                groups[group]["models"].add(model)
        elif dst.kind == "rawsql":
            for tid in rawsql_tables.get(e.dst, ()):
                groups[group]["tables"].add(tid)
                endpoint_table[e.src].add(tid)

    lines = ["flowchart LR"]
    by_kind: dict[str, list[ImpactNode]] = defaultdict(list)
    for nid in kept:
        by_kind[g.nodes[nid].kind].append(g.nodes[nid])
    for kind in ("table", "model"):
        nodes = by_kind.get(kind)
        if not nodes:
            continue
        lines.append(f"    subgraph {kind}")
        for n in sorted(nodes, key=lambda x: x.id):
            lines.append(f'        {n.id}["{n.label}"]')
        lines.append("    end")

    endpoint_counts: dict[str, int] = defaultdict(int)
    for nid in endpoints:
        endpoint_counts[endpoint_group(g.nodes[nid].label)] += 1
    lines.append("    subgraph endpoint")
    for group in sorted(groups):
        nid = f"epg_{_mid(group)}"
        lines.append(f'        {nid}["{group} — {endpoint_counts[group]} endpoints"]')
    lines.append("    end")

    shown: set[tuple[str, str, str]] = set()
    for e in g.edges:
        if e.kind == "maps_to" and e.src in kept and e.dst in kept:
            shown.add((e.src, e.dst, e.kind))
    for group, acc in groups.items():
        nid = f"epg_{_mid(group)}"
        for tid in acc["tables"]:
            shown.add((nid, tid, "queries"))
        if not acc["tables"]:
            for mid in acc["models"]:
                shown.add((nid, mid, "uses"))

    for src, dst, kind in sorted(shown):
        lines.append(f"    {src} -->|{kind}| {dst}")
    return "\n".join(lines)
