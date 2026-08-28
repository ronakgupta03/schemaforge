export interface VerifyJson {
  alembic_ok: boolean;
  pytest_ok: boolean;
  parity_ok: boolean | null;
  alembic_output?: string;
  pytest_output?: string;
  parity_output?: string;
  diff: Record<string, string[]>;
  explain: Array<{ query: string; ms: number; ms_before: number | null }>;
}

export function parseVerify(raw: string | null): VerifyJson | null {
  if (!raw) return null;
  try {
    const j = JSON.parse(raw) as Partial<VerifyJson>;
    if (typeof j !== "object" || j === null) return null;
    if (typeof j.alembic_ok !== "boolean" || typeof j.pytest_ok !== "boolean") return null;

    const explain = Array.isArray(j.explain)
      ? j.explain
          .filter(
            (e): e is { query: string; ms: number; ms_before: number | null } =>
              typeof e === "object" && e !== null && typeof e.query === "string" && typeof e.ms === "number",
          )
          .map((e) => ({
            query: e.query,
            ms: e.ms,
            ms_before: typeof e.ms_before === "number" ? e.ms_before : null,
          }))
      : [];

    const diff: Record<string, string[]> =
      typeof j.diff === "object" && j.diff !== null && !Array.isArray(j.diff)
        ? (j.diff as Record<string, string[]>)
        : {};

    return {
      alembic_ok: j.alembic_ok,
      pytest_ok: j.pytest_ok,
      parity_ok: typeof j.parity_ok === "boolean" ? j.parity_ok : null,
      alembic_output: typeof j.alembic_output === "string" ? j.alembic_output : undefined,
      pytest_output: typeof j.pytest_output === "string" ? j.pytest_output : undefined,
      parity_output: typeof j.parity_output === "string" ? j.parity_output : undefined,
      diff,
      explain,
    };
  } catch { return null; }
}

export function badges(v: VerifyJson | null): Array<{ label: string; ok: boolean | null }> {
  if (!v) return [
    { label: "Migration", ok: null },
    { label: "Tests", ok: null },
    { label: "Parity", ok: null },
  ];
  return [
    { label: "Migration", ok: v.alembic_ok },
    { label: "Tests", ok: v.pytest_ok },
    { label: "Parity", ok: v.parity_ok ?? null },
  ];
}
