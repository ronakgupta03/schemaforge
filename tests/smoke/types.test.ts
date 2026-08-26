/**
 * Smoke tests – verify the project starts and core types can be instantiated.
 *
 * These tests do NOT call any external services, LLMs, databases, or MCP servers.
 */

import { randomUUID } from "crypto";
import {
  MigrationRequestSchema,
  DatabaseFindingsSchema,
  ASTFindingsSchema,
  ImpactGraphSchema,
  MigrationPlanSchema,
  SafetyReportSchema,
  ApprovalStateSchema,
} from "../../src/types";

// ---------------------------------------------------------------------------
// MigrationRequest
// ---------------------------------------------------------------------------

describe("MigrationRequest", () => {
  const valid = {
    id: randomUUID(),
    description: "Split users table",
    type: "split_table" as const,
    targetTable: "users",
    createdAt: new Date().toISOString(),
  };

  it("parses a valid request", () => {
    const result = MigrationRequestSchema.safeParse(valid);
    expect(result.success).toBe(true);
  });

  it("rejects a request with empty description", () => {
    const result = MigrationRequestSchema.safeParse({ ...valid, description: "" });
    expect(result.success).toBe(false);
  });

  it("rejects an unknown migration type", () => {
    const result = MigrationRequestSchema.safeParse({ ...valid, type: "teleport_table" });
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// DatabaseFindings
// ---------------------------------------------------------------------------

describe("DatabaseFindings", () => {
  const valid = {
    requestId: randomUUID(),
    dialect: "postgres" as const,
    tables: [
      {
        name: "users",
        columns: [
          {
            name: "id",
            dataType: "uuid",
            nullable: false,
            isPrimaryKey: true,
            isForeignKey: false,
            hasIndex: true,
          },
          {
            name: "email",
            dataType: "varchar(255)",
            nullable: false,
            isPrimaryKey: false,
            isForeignKey: false,
            hasIndex: true,
          },
        ],
      },
    ],
    foreignKeys: [],
    affectedTables: ["users"],
    analysedAt: new Date().toISOString(),
  };

  it("parses valid database findings", () => {
    const result = DatabaseFindingsSchema.safeParse(valid);
    expect(result.success).toBe(true);
  });

  it("rejects an unsupported dialect", () => {
    const result = DatabaseFindingsSchema.safeParse({ ...valid, dialect: "oracle" });
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// ASTFindings
// ---------------------------------------------------------------------------

describe("ASTFindings", () => {
  const valid = {
    requestId: randomUUID(),
    rootDir: "/app/src",
    codeReferences: [
      {
        filePath: "/app/src/models/user.ts",
        startLine: 10,
        endLine: 45,
        kind: "orm_model_reference" as const,
        references: ["users"],
      },
    ],
    filesScanned: 120,
    analysedAt: new Date().toISOString(),
  };

  it("parses valid AST findings", () => {
    const result = ASTFindingsSchema.safeParse(valid);
    expect(result.success).toBe(true);
  });

  it("rejects a code reference with a zero start line", () => {
    const badRef = { ...valid.codeReferences[0], startLine: 0 };
    const result = ASTFindingsSchema.safeParse({
      ...valid,
      codeReferences: [badRef],
    });
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// ImpactGraph
// ---------------------------------------------------------------------------

describe("ImpactGraph", () => {
  const valid = {
    requestId: randomUUID(),
    nodes: [
      { id: "table:users", kind: "table" as const, label: "users", direct: true },
      { id: "file:models/user.ts", kind: "file" as const, label: "user.ts", direct: false },
    ],
    edges: [
      {
        fromId: "file:models/user.ts",
        toId: "table:users",
        relationship: "references",
      },
    ],
    rootNodes: ["table:users"],
    builtAt: new Date().toISOString(),
  };

  it("parses a valid impact graph", () => {
    const result = ImpactGraphSchema.safeParse(valid);
    expect(result.success).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// MigrationPlan
// ---------------------------------------------------------------------------

describe("MigrationPlan", () => {
  const valid = {
    requestId: randomUUID(),
    steps: [
      {
        stepIndex: 0,
        kind: "schema_ddl" as const,
        description: "Create user_accounts table",
        risk: "medium" as const,
        reversible: true,
      },
      {
        stepIndex: 1,
        kind: "data_backfill" as const,
        description: "Backfill user_accounts from users",
        risk: "high" as const,
        reversible: false,
      },
    ],
    requiresDowntime: false,
    plannedAt: new Date().toISOString(),
  };

  it("parses a valid migration plan", () => {
    const result = MigrationPlanSchema.safeParse(valid);
    expect(result.success).toBe(true);
  });

  it("rejects a step with an unknown risk level", () => {
    const badStep = { ...valid.steps[0], risk: "critical" };
    const result = MigrationPlanSchema.safeParse({
      ...valid,
      steps: [badStep],
    });
    expect(result.success).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// SafetyReport
// ---------------------------------------------------------------------------

describe("SafetyReport", () => {
  const valid = {
    requestId: randomUUID(),
    checks: [
      {
        name: "foreign_key_integrity",
        result: "pass" as const,
        message: "All FK constraints satisfied",
        ranInSandbox: false,
      },
    ],
    overall: "pass" as const,
    generatedAt: new Date().toISOString(),
  };

  it("parses a valid safety report", () => {
    const result = SafetyReportSchema.safeParse(valid);
    expect(result.success).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// ApprovalState
// ---------------------------------------------------------------------------

describe("ApprovalState", () => {
  it("parses a pending approval state", () => {
    const result = ApprovalStateSchema.safeParse({
      requestId: randomUUID(),
      status: "pending",
      updatedAt: new Date().toISOString(),
    });
    expect(result.success).toBe(true);
  });

  it("parses an approved state with approver", () => {
    const result = ApprovalStateSchema.safeParse({
      requestId: randomUUID(),
      status: "approved",
      approvedBy: "alice@example.com",
      updatedAt: new Date().toISOString(),
    });
    expect(result.success).toBe(true);
  });

  it("rejects an unknown status", () => {
    const result = ApprovalStateSchema.safeParse({
      requestId: randomUUID(),
      status: "maybe",
      updatedAt: new Date().toISOString(),
    });
    expect(result.success).toBe(false);
  });
});
