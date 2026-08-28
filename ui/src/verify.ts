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
    const j = JSON.parse(raw) as VerifyJson;
    if (typeof j.alembic_ok !== "boolean" || typeof j.pytest_ok !== "boolean") return null;
    return j;
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
