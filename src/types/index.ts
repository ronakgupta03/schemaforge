/**
 * SchemaForge – Shared Types
 *
 * All domain types are defined here with Zod schemas for runtime validation
 * and TypeScript types inferred from them for compile-time safety.
 *
 * Pipeline stages (each type corresponds to one stage):
 *   MigrationRequest
 *   → DatabaseFindings
 *   → ASTFindings
 *   → ImpactGraph
 *   → MigrationPlan
 *   → SafetyReport
 *   → ApprovalState
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Primitives
// ---------------------------------------------------------------------------

export const TableNameSchema = z.string().min(1);
export const ColumnNameSchema = z.string().min(1);
export const FilePathSchema = z.string().min(1);

// ---------------------------------------------------------------------------
// MigrationRequest — what the user asks SchemaForge to do
// ---------------------------------------------------------------------------

export const MigrationTypeSchema = z.enum([
  "split_table",
  "rename_column",
  "add_column",
  "drop_column",
  "change_type",
  "add_index",
  "custom",
]);

export type MigrationType = z.infer<typeof MigrationTypeSchema>;

export const MigrationRequestSchema = z.object({
  /** Unique identifier for this migration run */
  id: z.string().uuid(),
  /** Human-readable description of what the migration should accomplish */
  description: z.string().min(1),
  /** Specific migration operation type */
  type: MigrationTypeSchema,
  /** Target database table */
  targetTable: TableNameSchema,
  /** Optional additional parameters (e.g. columns involved, new table names) */
  params: z.record(z.string(), z.unknown()).optional(),
  /** ISO-8601 timestamp when the request was created */
  createdAt: z.string().datetime(),
});

export type MigrationRequest = z.infer<typeof MigrationRequestSchema>;

// ---------------------------------------------------------------------------
// DatabaseFindings — what was discovered about the DB schema
// ---------------------------------------------------------------------------

export const ColumnSchema = z.object({
  name: ColumnNameSchema,
  dataType: z.string(),
  nullable: z.boolean(),
  isPrimaryKey: z.boolean(),
  isForeignKey: z.boolean(),
  referencedTable: TableNameSchema.optional(),
  referencedColumn: ColumnNameSchema.optional(),
  hasIndex: z.boolean(),
});

export type Column = z.infer<typeof ColumnSchema>;

export const TableSchema = z.object({
  name: TableNameSchema,
  columns: z.array(ColumnSchema),
  rowCountEstimate: z.number().int().nonnegative().optional(),
});

export type Table = z.infer<typeof TableSchema>;

export const ForeignKeyConstraintSchema = z.object({
  constraintName: z.string(),
  fromTable: TableNameSchema,
  fromColumn: ColumnNameSchema,
  toTable: TableNameSchema,
  toColumn: ColumnNameSchema,
});

export type ForeignKeyConstraint = z.infer<typeof ForeignKeyConstraintSchema>;

export const DatabaseFindingsSchema = z.object({
  requestId: z.string().uuid(),
  dialect: z.enum(["postgres", "mysql", "sqlite"]),
  tables: z.array(TableSchema),
  foreignKeys: z.array(ForeignKeyConstraintSchema),
  /** Tables/columns directly affected by the planned migration */
  affectedTables: z.array(TableNameSchema),
  analysedAt: z.string().datetime(),
});

export type DatabaseFindings = z.infer<typeof DatabaseFindingsSchema>;

// ---------------------------------------------------------------------------
// ASTFindings — what was discovered by static analysis of application code
// ---------------------------------------------------------------------------

export const ASTFindingKindSchema = z.enum([
  "orm_model_reference",
  "raw_sql_query",
  "dao_method",
  "service_call",
  "test_fixture",
  "migration_file",
  "unknown",
]);

export type ASTFindingKind = z.infer<typeof ASTFindingKindSchema>;

export const CodeReferenceSchema = z.object({
  filePath: FilePathSchema,
  /** 1-based start line */
  startLine: z.number().int().positive(),
  /** 1-based end line */
  endLine: z.number().int().positive(),
  /** Relevant source snippet (optional – may be omitted for large blobs) */
  snippet: z.string().optional(),
  kind: ASTFindingKindSchema,
  /** Table or column names referenced at this location */
  references: z.array(z.string()),
});

export type CodeReference = z.infer<typeof CodeReferenceSchema>;

export const ASTFindingsSchema = z.object({
  requestId: z.string().uuid(),
  /** Root directory that was analysed */
  rootDir: FilePathSchema,
  /** All code locations that reference affected schema objects */
  codeReferences: z.array(CodeReferenceSchema),
  /** Number of files scanned */
  filesScanned: z.number().int().nonnegative(),
  analysedAt: z.string().datetime(),
});

export type ASTFindings = z.infer<typeof ASTFindingsSchema>;

// ---------------------------------------------------------------------------
// ImpactGraph — combined dependency graph of DB + code findings
// ---------------------------------------------------------------------------

export const ImpactNodeKindSchema = z.enum([
  "table",
  "column",
  "file",
  "service",
  "test",
]);

export type ImpactNodeKind = z.infer<typeof ImpactNodeKindSchema>;

export const ImpactNodeSchema = z.object({
  id: z.string(),
  kind: ImpactNodeKindSchema,
  label: z.string(),
  /** Whether this node is directly affected (vs. transitively affected) */
  direct: z.boolean(),
});

export type ImpactNode = z.infer<typeof ImpactNodeSchema>;

export const ImpactEdgeSchema = z.object({
  fromId: z.string(),
  toId: z.string(),
  /** Human-readable relationship label */
  relationship: z.string(),
});

export type ImpactEdge = z.infer<typeof ImpactEdgeSchema>;

export const ImpactGraphSchema = z.object({
  requestId: z.string().uuid(),
  nodes: z.array(ImpactNodeSchema),
  edges: z.array(ImpactEdgeSchema),
  /** Nodes that are the root cause of the migration ripple effect */
  rootNodes: z.array(z.string()),
  builtAt: z.string().datetime(),
});

export type ImpactGraph = z.infer<typeof ImpactGraphSchema>;

// ---------------------------------------------------------------------------
// MigrationPlan — ordered list of migration steps
// ---------------------------------------------------------------------------

export const MigrationStepKindSchema = z.enum([
  "schema_ddl",
  "data_backfill",
  "code_change",
  "test_update",
  "rollback_ddl",
]);

export type MigrationStepKind = z.infer<typeof MigrationStepKindSchema>;

export const MigrationStepSchema = z.object({
  stepIndex: z.number().int().nonnegative(),
  kind: MigrationStepKindSchema,
  description: z.string(),
  /** Estimated risk level for this step */
  risk: z.enum(["low", "medium", "high"]),
  /** Whether this step is reversible */
  reversible: z.boolean(),
  /** Artefact to be produced (file path, SQL statement, etc.) – NOT YET GENERATED */
  artefact: z.string().optional(),
});

export type MigrationStep = z.infer<typeof MigrationStepSchema>;

export const MigrationPlanSchema = z.object({
  requestId: z.string().uuid(),
  steps: z.array(MigrationStepSchema),
  estimatedDurationMinutes: z.number().nonnegative().optional(),
  requiresDowntime: z.boolean(),
  plannedAt: z.string().datetime(),
});

export type MigrationPlan = z.infer<typeof MigrationPlanSchema>;

// ---------------------------------------------------------------------------
// SafetyReport — pre-merge validation summary
// ---------------------------------------------------------------------------

export const SafetyCheckResultSchema = z.enum(["pass", "warn", "fail", "skipped"]);
export type SafetyCheckResult = z.infer<typeof SafetyCheckResultSchema>;

export const SafetyCheckSchema = z.object({
  name: z.string(),
  result: SafetyCheckResultSchema,
  message: z.string(),
  /** ⚠️ NOT YET IMPLEMENTED: sandbox execution is not available in this version */
  ranInSandbox: z.boolean(),
});

export type SafetyCheck = z.infer<typeof SafetyCheckSchema>;

export const SafetyReportSchema = z.object({
  requestId: z.string().uuid(),
  checks: z.array(SafetyCheckSchema),
  /** Overall result – fails if any individual check fails */
  overall: SafetyCheckResultSchema,
  generatedAt: z.string().datetime(),
});

export type SafetyReport = z.infer<typeof SafetyReportSchema>;

// ---------------------------------------------------------------------------
// ApprovalState — human-in-the-loop gate
// ---------------------------------------------------------------------------

export const ApprovalStatusSchema = z.enum([
  "pending",
  "approved",
  "rejected",
  "auto_approved",
]);

export type ApprovalStatus = z.infer<typeof ApprovalStatusSchema>;

export const ApprovalStateSchema = z.object({
  requestId: z.string().uuid(),
  status: ApprovalStatusSchema,
  /** Human who approved/rejected – undefined when pending or auto-approved */
  approvedBy: z.string().optional(),
  /** Rejection reason – only present when status === 'rejected' */
  rejectionReason: z.string().optional(),
  updatedAt: z.string().datetime(),
});

export type ApprovalState = z.infer<typeof ApprovalStateSchema>;
