import { describe, it, expect } from "vitest";
import { parseUnifiedDiff } from "./diff";

const patch = [
  "diff --git a/demo-app/app/models.py b/demo-app/app/models.py",
  "index 111..222 100644",
  "--- a/demo-app/app/models.py",
  "+++ b/demo-app/app/models.py",
  "@@ -10,3 +10,4 @@ class User(Base):",
  "     email: Mapped[str]",
  "-    address: Mapped[str]",
  "+    # address moved to UserProfile",
  "     name: Mapped[str]",
  "",
].join("\n");

describe("parseUnifiedDiff", () => {
  it("skips header lines before the first hunk", () => {
    const lines = parseUnifiedDiff(patch);
    expect(lines.every((l) => l.kind !== "meta" || l.text.startsWith("---") || l.text.startsWith("+++"))).toBe(true);
  });
  it("classifies +/-/context lines", () => {
    const kinds = parseUnifiedDiff(patch).map((l) => l.kind);
    expect(kinds).toContain("add");
    expect(kinds).toContain("del");
    expect(kinds).toContain("ctx");
    expect(kinds).toContain("hunk");
  });
  it("drops diff --git/index noise", () => {
    expect(parseUnifiedDiff(patch).some((l) => l.text.startsWith("diff --git"))).toBe(false);
  });
  it("returns [] for empty input", () => {
    expect(parseUnifiedDiff("")).toEqual([]);
  });
});
