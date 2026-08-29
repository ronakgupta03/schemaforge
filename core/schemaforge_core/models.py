"""SchemaForge core data model: DB snapshot, code facts, impact graph.

All types are plain dataclasses with to_dict/from_dict so the pipeline can
pass everything between stages as JSON (and the LLM can read it).
"""
from __future__ import annotations

from dataclasses import InitVar, asdict, dataclass, field


@dataclass
class ColumnInfo:
    name: str
    data_type: str = ""
    nullable: bool = True
    default: str | None = None
    type: InitVar[str | None] = None

    def __post_init__(self, type: str | None = None) -> None:
        if type is not None and not self.data_type:
            self.data_type = type

@dataclass
class IndexInfo:
    name: str
    columns: list[str] = field(default_factory=list)
    unique: bool = False


@dataclass
class ForeignKeyInfo:
    name: str
    column: str
    ref_table: str
    ref_column: str


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    row_count: int | None = None  # pg_class.reltuples estimate


@dataclass
class DBSnapshot:
    tables: dict[str, TableInfo] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> DBSnapshot:
        snap = cls()
        for name, t in d.get("tables", {}).items():
            snap.tables[name] = TableInfo(
                name=t["name"],
                columns=[ColumnInfo(**c) for c in t["columns"]],
                indexes=[IndexInfo(**i) for i in t["indexes"]],
                foreign_keys=[ForeignKeyInfo(**f) for f in t["foreign_keys"]],
                row_count=t.get("row_count"),
            )
        return snap


@dataclass
class ModelFact:
    """A SQLAlchemy declarative model class (name ↔ table mapping)."""

    name: str
    table: str
    columns: list[str]
    file: str
    line: int


@dataclass
class AttrAccess:
    """An attribute read of a known model column on a model-typed variable."""

    model: str
    column: str
    file: str
    line: int
    function: str


@dataclass
class RawSqlRef:
    """A raw SQL string (text(...) / execute(...)) and the tables it touches."""

    tables: list[str]
    file: str
    line: int
    function: str


@dataclass
class EndpointFact:
    """A FastAPI route."""

    path: str
    method: str
    file: str
    line: int
    function: str


@dataclass
class FunctionCall:
    """A call from one function to another in the same file (for impact edges)."""

    caller: str
    callee: str
    file: str
    line: int


@dataclass
class CodeFacts:
    models: list[ModelFact] = field(default_factory=list)
    attr_accesses: list[AttrAccess] = field(default_factory=list)
    raw_sql: list[RawSqlRef] = field(default_factory=list)
    endpoints: list[EndpointFact] = field(default_factory=list)
    calls: list[FunctionCall] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> CodeFacts:
        return cls(
            models=[ModelFact(**m) for m in d.get("models", [])],
            attr_accesses=[AttrAccess(**a) for a in d.get("attr_accesses", [])],
            raw_sql=[RawSqlRef(**r) for r in d.get("raw_sql", [])],
            endpoints=[EndpointFact(**e) for e in d.get("endpoints", [])],
            calls=[FunctionCall(**c) for c in d.get("calls", [])],
        )


@dataclass
class ImpactNode:
    id: str
    kind: str  # table | column | model | attr | rawsql | endpoint
    label: str
    file: str | None = None


@dataclass
class ImpactEdge:
    src: str
    dst: str
    kind: str  # has_column | maps_to | defines_column | accessed_via | queries | executes


@dataclass
class ImpactGraph:
    nodes: dict[str, ImpactNode] = field(default_factory=dict)
    edges: list[ImpactEdge] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ImpactGraph:
        return cls(
            nodes={k: ImpactNode(**v) for k, v in d.get("nodes", {}).items()},
            edges=[ImpactEdge(**e) for e in d.get("edges", [])],
        )