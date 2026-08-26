/**
 * SchemaForge – Pipeline Orchestrator
 *
 * Coordinates the end-to-end migration pipeline:
 *
 *   MigrationRequest
 *     → [DB Analysis]      (via TrueForge DB Analyser agent)
 *     → [AST Analysis]     (via TrueForge AST Analyser agent)
 *     → [Impact Graph]     (via TrueForge Impact Graph Builder)
 *     → [Migration Plan]   (via TrueForge Plan Generator)
 *     → [Safety Report]    (via TrueForge Safety Checker – sandbox NOT YET IMPL.)
 *     → [Human Approval]   (blocking gate – NOT YET IMPLEMENTED)
 *     → Production
 *
 * ⚠️  Most pipeline stages are NOT YET IMPLEMENTED.
 *     The orchestrator skeleton is runnable; it will throw NotImplementedError
 *     at the first agent call until TrueForge is wired in.
 */

import { logger } from "./logger";
import type { ITrueForgeAdapter } from "./integrations/trueforge";
import type {
  ApprovalState,
  ImpactGraph,
  MigrationPlan,
  MigrationRequest,
  SafetyReport,
} from "./types";
import { ApprovalStatusSchema } from "./types";
import { NotImplementedError } from "./errors";

// ---------------------------------------------------------------------------
// Pipeline result
// ---------------------------------------------------------------------------

export interface PipelineResult {
  request: MigrationRequest;
  /** undefined until the stage runs */
  impactGraph?: ImpactGraph;
  plan?: MigrationPlan;
  safetyReport?: SafetyReport;
  approval?: ApprovalState;
  /** Indicates which stage the pipeline reached before stopping */
  reachedStage:
    | "request_received"
    | "db_analysed"
    | "ast_analysed"
    | "impact_graph_built"
    | "plan_generated"
    | "safety_checked"
    | "approved"
    | "complete";
}

// ---------------------------------------------------------------------------
// Orchestrator
// ---------------------------------------------------------------------------

export class Orchestrator {
  constructor(private readonly trueForge: ITrueForgeAdapter) {}

  /**
   * Run the full migration pipeline for a given request.
   * Stages that are not yet implemented will surface a NotImplementedError.
   */
  async run(request: MigrationRequest): Promise<PipelineResult> {
    logger.info("Pipeline started", {
      requestId: request.id,
      type: request.type,
      targetTable: request.targetTable,
    });

    const result: PipelineResult = {
      request,
      reachedStage: "request_received",
    };

    // ── Stage 1: DB Analysis ────────────────────────────────────────────────
    logger.info("Stage 1/5: DB Analysis", { requestId: request.id });
    const dbFindings = await this.trueForge.analyseDatabase(request);
    result.reachedStage = "db_analysed";

    // ── Stage 2: AST Analysis ───────────────────────────────────────────────
    logger.info("Stage 2/5: AST Analysis", { requestId: request.id });
    const astFindings = await this.trueForge.analyseAST(request, dbFindings);
    result.reachedStage = "ast_analysed";

    // ── Stage 3: Impact Graph ───────────────────────────────────────────────
    logger.info("Stage 3/5: Building Impact Graph", { requestId: request.id });
    const impactGraph = await this.trueForge.buildImpactGraph(
      request,
      dbFindings,
      astFindings,
    );
    result.impactGraph = impactGraph;
    result.reachedStage = "impact_graph_built";

    // ── Stage 4: Migration Plan ─────────────────────────────────────────────
    logger.info("Stage 4/5: Generating Migration Plan", {
      requestId: request.id,
    });
    const plan = await this.trueForge.generatePlan(request, impactGraph);
    result.plan = plan;
    result.reachedStage = "plan_generated";

    // ── Stage 5: Safety Checks ──────────────────────────────────────────────
    logger.info("Stage 5/5: Running Safety Checks", { requestId: request.id });
    const safetyReport = await this.trueForge.runSafetyChecks(request, plan);
    result.safetyReport = safetyReport;
    result.reachedStage = "safety_checked";

    // ── Gate: Human Approval (NOT YET IMPLEMENTED) ──────────────────────────
    // Production execution is blocked until this gate is wired in.
    logger.warn(
      "Human approval gate is NOT YET IMPLEMENTED – pipeline halted before production.",
      { requestId: request.id },
    );
    throw new NotImplementedError("Human approval gate");
  }

  /**
   * Dry-run: validates the request and returns immediately.
   * Useful for testing the pipeline skeleton without any agent calls.
   */
  dryRun(request: MigrationRequest): PipelineResult {
    logger.info("Dry-run: pipeline validated (no agent calls made)", {
      requestId: request.id,
    });

    const approval: ApprovalState = {
      requestId: request.id,
      status: ApprovalStatusSchema.enum.pending,
      updatedAt: new Date().toISOString(),
    };

    return {
      request,
      approval,
      reachedStage: "request_received",
    };
  }
}
