/**
 * SchemaForge – Application Entry Point
 *
 * This file bootstraps the SchemaForge application.
 * In this initial skeleton, it:
 *   1. Loads configuration and validates env vars.
 *   2. Initialises the logger.
 *   3. Instantiates the Orchestrator with the stub TrueForge adapter.
 *   4. Performs a dry-run with a sample MigrationRequest.
 *
 * Running: pnpm run dev
 *
 * ⚠️  The following features are NOT YET IMPLEMENTED:
 *   - Live database analysis
 *   - AST / code scanning
 *   - LLM-powered migration planning
 *   - Sandbox execution
 *   - Human approval gate
 *   - Production execution
 */

import { config } from "./config";
import { logger } from "./logger";
import { Orchestrator } from "./orchestrator";
import { StubTrueForgeAdapter } from "./integrations/trueforge";
import { MigrationRequestSchema } from "./types";
import { randomUUID } from "crypto";

function main(): void {
  logger.info("SchemaForge starting", {
    env: config.env,
    logLevel: config.logLevel,
    googleApiKeyConfigured: Boolean(config.googleApiKey),
    databaseUrlConfigured: Boolean(config.databaseUrl),
  });

  // ── Build a sample request (users-split example) ─────────────────────────
  const rawRequest = {
    id: randomUUID(),
    description:
      "Split the monolithic `users` table into `user_accounts` and `user_profiles`.",
    type: "split_table",
    targetTable: "users",
    params: {
      newTables: ["user_accounts", "user_profiles"],
    },
    createdAt: new Date().toISOString(),
  };

  // Validate at the boundary
  const request = MigrationRequestSchema.parse(rawRequest);
  logger.info("Migration request created", {
    requestId: request.id,
    type: request.type,
  });

  // ── Orchestrate (dry-run in skeleton mode) ────────────────────────────────
  const adapter = new StubTrueForgeAdapter();
  const orchestrator = new Orchestrator(adapter);
  const result = orchestrator.dryRun(request);

  logger.info("Dry-run complete", {
    requestId: result.request.id,
    reachedStage: result.reachedStage,
    approvalStatus: result.approval?.status,
  });

  logger.info(
    "SchemaForge skeleton is operational. " +
      "Connect TrueForge adapters to enable the full analysis pipeline.",
  );
}

try {
  main();
} catch (err: unknown) {
  const message = err instanceof Error ? err.message : String(err);
  logger.error("Fatal error during startup", { error: message });
  process.exit(1);
}
