import { describe, it, expect } from "vitest";
import { parseVerify, badges } from "./verify";

const good = JSON.stringify({
  alembic_ok: true, pytest_ok: true, parity_ok: true,
  diff: { added_tables: ["user_profiles"], removed_tables: [], added_columns: [], removed_columns: ["users.address", "users.date_of_birth"] },
  explain: [{ query: "find_by_email", ms: 1.4, ms_before: 1.4 }],
});

describe("parseVerify", () => {
  it("parses valid JSON", () => {
    const v = parseVerify(good);
    expect(v?.alembic_ok).toBe(true);
    expect(v?.diff.added_tables).toEqual(["user_profiles"]);
  });
  it("returns null on invalid JSON", () => {
    expect(parseVerify("not json")).toBeNull();
    expect(parseVerify("")).toBeNull();
  });
  it("normalizes malformed explain and diff fields", () => {
    const malformed = JSON.stringify({
      alembic_ok: true,
      pytest_ok: true,
      explain: "oops",
      diff: null,
    });
    const v = parseVerify(malformed);
    expect(v).not.toBeNull();
    expect(v?.alembic_ok).toBe(true);
    expect(v?.pytest_ok).toBe(true);
    expect(Array.isArray(v?.explain)).toBe(true);
    expect(v?.explain).toEqual([]);
    expect(v?.diff).toEqual({});
  });
});

describe("badges", () => {
  it("maps ok fields to badges", () => {
    const b = badges(parseVerify(good));
    expect(b).toEqual([
      { label: "Migration", ok: true },
      { label: "Tests", ok: true },
      { label: "Parity", ok: true },
    ]);
  });
  it("treats null parity as neutral (null ok)", () => {
    const v = parseVerify(JSON.stringify({ alembic_ok: true, pytest_ok: false, parity_ok: null }));
    const b = badges(v);
    expect(b[2]).toEqual({ label: "Parity", ok: null });
  });
  it("returns neutral badges for unparsable input", () => {
    expect(badges(null).every((b) => b.ok === null)).toBe(true);
  });
});
