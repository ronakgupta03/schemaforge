/**
 * SchemaForge – TrueForge Integration Point
 *
 * TrueForge is Google's agent orchestration framework used to power the
 * SchemaForge analysis pipeline. This module defines the adapter interface
 * between SchemaForge's domain types and TrueForge's agent runner.
 *
 * ⚠️  NOT YET IMPLEMENTED
 * This file currently contains the interface contract only.
 * Concrete implementation will follow once TrueForge is wired in.
 *
 * Architecture intent:
 *  SchemaForge domain types  ──►  TrueForgeAdapter  ──►  TrueForge Agent Runner
 *                                       │
 *                                       ▼
 *                               Tool calls / MCP servers
 *                               (DB analysis, AST scanner, sandbox)
 */

import { NotImplementedError } from "../errors";
import type {
  ASTFindings,
  DatabaseFindings,
  ImpactGraph,
  MigrationPlan,
  MigrationRequest,
  SafetyReport,
} from "../types";

// ---------------------------------------------------------------------------
// TrueForge agent identifiers used by SchemaForge
// ---------------------------------------------------------------------------

export const TRUEFORGE_AGENT_IDS = {
  /** Analyses the live database schema */
  DB_ANALYSER: "schemaforge.db_analyser",
  /** Runs static AST analysis over the codebase */
  AST_ANALYSER: "schemaforge.ast_analyser",
  /** Builds the combined impact graph */
  IMPACT_GRAPH_BUILDER: "schemaforge.impact_graph_builder",
  /** Generates the migration plan */
  PLAN_GENERATOR: "schemaforge.plan_generator",
  /** Executes safety checks (sandbox – not yet available) */
  SAFETY_CHECKER: "schemaforge.safety_checker",
} as const;

export type TrueForgeAgentId =
  (typeof TRUEFORGE_AGENT_IDS)[keyof typeof TRUEFORGE_AGENT_IDS];

// ---------------------------------------------------------------------------
// Adapter interface
// ---------------------------------------------------------------------------

/**
 * ITrueForgeAdapter – the contract SchemaForge expects from its TrueForge
 * integration layer.
 *
 * Each method corresponds to one stage of the analysis pipeline.
 * All methods return Promises so they can be backed by async agent calls.
 */
export interface ITrueForgeAdapter {
  /**
   * Run database schema analysis for a given migration request.
   * ⚠️ NOT YET IMPLEMENTED
   */
  analyseDatabase(request: MigrationRequest): Promise<DatabaseFindings>;

  /**
   * Run static AST analysis over the codebase.
   * ⚠️ NOT YET IMPLEMENTED
   */
  analyseAST(
    request: MigrationRequest,
    dbFindings: DatabaseFindings,
  ): Promise<ASTFindings>;

  /**
   * Build the impact graph from DB + AST findings.
   * ⚠️ NOT YET IMPLEMENTED
   */
  buildImpactGraph(
    request: MigrationRequest,
    dbFindings: DatabaseFindings,
    astFindings: ASTFindings,
  ): Promise<ImpactGraph>;

  /**
   * Generate the migration plan from the impact graph.
   * ⚠️ NOT YET IMPLEMENTED
   */
  generatePlan(
    request: MigrationRequest,
    impactGraph: ImpactGraph,
  ): Promise<MigrationPlan>;

  /**
   * Run safety checks against the generated plan.
   * Sandbox execution is NOT YET IMPLEMENTED.
   * ⚠️ NOT YET IMPLEMENTED
   */
  runSafetyChecks(
    request: MigrationRequest,
    plan: MigrationPlan,
  ): Promise<SafetyReport>;
}

// ---------------------------------------------------------------------------
// Stub implementation (used until TrueForge is wired in)
// ---------------------------------------------------------------------------

/**
 * StubTrueForgeAdapter – throws NotImplementedError for every method.
 * Keeps the orchestrator runnable without a live TrueForge connection.
 */
export class StubTrueForgeAdapter implements ITrueForgeAdapter {
  analyseDatabase(_request: MigrationRequest): Promise<DatabaseFindings> {
    return Promise.reject(
      new NotImplementedError(
        `${TRUEFORGE_AGENT_IDS.DB_ANALYSER} (TrueForge DB analysis)`,
      ),
    );
  }

  analyseAST(
    _request: MigrationRequest,
    _dbFindings: DatabaseFindings,
  ): Promise<ASTFindings> {
    return Promise.reject(
      new NotImplementedError(
        `${TRUEFORGE_AGENT_IDS.AST_ANALYSER} (TrueForge AST analysis)`,
      ),
    );
  }

  buildImpactGraph(
    _request: MigrationRequest,
    _dbFindings: DatabaseFindings,
    _astFindings: ASTFindings,
  ): Promise<ImpactGraph> {
    return Promise.reject(
      new NotImplementedError(
        `${TRUEFORGE_AGENT_IDS.IMPACT_GRAPH_BUILDER} (TrueForge impact graph)`,
      ),
    );
  }

  generatePlan(
    _request: MigrationRequest,
    _impactGraph: ImpactGraph,
  ): Promise<MigrationPlan> {
    return Promise.reject(
      new NotImplementedError(
        `${TRUEFORGE_AGENT_IDS.PLAN_GENERATOR} (TrueForge plan generator)`,
      ),
    );
  }

  runSafetyChecks(
    _request: MigrationRequest,
    _plan: MigrationPlan,
  ): Promise<SafetyReport> {
    return Promise.reject(
      new NotImplementedError(
        `${TRUEFORGE_AGENT_IDS.SAFETY_CHECKER} (TrueForge safety checker / sandbox)`,
      ),
    );
  }
}
