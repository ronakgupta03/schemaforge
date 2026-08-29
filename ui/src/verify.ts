// Tool-aware verification report schema. The backend emits both the neutral
// keys (apply_ok / test_ok / apply_output / test_output) and, for backward
// compatibility with older verify.json files, the legacy alembic_ok /
// pytest_ok / alembic_output / pytest_output aliases. parseVerify accepts
// either set so existing reports keep rendering while the labels become
// tool-aware (Alembic vs SQL).

export interface VerifyJson {
  tool: "alembic" | "sql" | string;
  apply_ok: boolean;
  test_ok: boolean;
  parity_ok: boolean | null;
  apply_output?: string;
  test_output?: string;
  parity_output?: string;
  diff: Record<string, string[]>;
  explain: Array<{ query: string; ms: number; ms_before: number | null }>;
}

function pickBool(
  j: Record<string, unknown>,
  primary: string,
  legacy: string,
): boolean | undefined {
  if (typeof j[primary] === "boolean") return j[primary] as boolean;
  if (typeof j[legacy] === "boolean") return j[legacy] as boolean;
  return undefined;
}

function pickStr(
  j: Record<string, unknown>,
  primary: string,
  legacy: string,
): string | undefined {
  if (typeof j[primary] === "string") return j[primary] as string;
  if (typeof j[legacy] === "string") return j[legacy] as string;
  return undefined;
}

export function parseVerify(raw: string | null): VerifyJson | null {
  if (!raw) return null;
  try {
    const j = JSON.parse(raw) as Record<string, unknown>;
    if (typeof j !== "object" || j === null) return null;

    const apply_ok = pickBool(j, "apply_ok", "alembic_ok");
    const test_ok = pickBool(j, "test_ok", "pytest_ok");
    if (typeof apply_ok !== "boolean" || typeof test_ok !== "boolean") return null;

    const explain = Array.isArray(j.explain)
      ? j.explain
          .filter(
            (e): e is { query: string; ms: number; ms_before: number | null } =>
              typeof e === "object" &&
              e !== null &&
              typeof e.query === "string" &&
              typeof e.ms === "number",
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
      tool: typeof j.tool === "string" ? j.tool : "alembic",
      apply_ok,
      test_ok,
      parity_ok: typeof j.parity_ok === "boolean" ? j.parity_ok : null,
      apply_output: pickStr(j, "apply_output", "alembic_output"),
      test_output: pickStr(j, "test_output", "pytest_output"),
      parity_output: typeof j.parity_output === "string" ? j.parity_output : undefined,
      diff,
      explain,
    };
  } catch {
    return null;
  }
}

export function badges(
  v: VerifyJson | null,
): Array<{ label: string; ok: boolean | null }> {
  if (!v)
    return [
      { label: "Migration", ok: null },
      { label: "Tests", ok: null },
      { label: "Parity", ok: null },
    ];
  return [
    { label: "Migration", ok: v.apply_ok },
    { label: "Tests", ok: v.test_ok },
    { label: "Parity", ok: v.parity_ok ?? null },
  ];
}

export function migrationLabel(v: VerifyJson | null): string {
  return v && v.tool === "sql" ? "SQL migration apply" : "Alembic migration";
}
