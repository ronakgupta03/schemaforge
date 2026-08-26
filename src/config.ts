/**
 * SchemaForge – Configuration
 *
 * All configuration is loaded from environment variables (via dotenv).
 * See .env.example for the full list of supported variables.
 *
 * Import this module once at startup (it is called automatically by main.ts).
 */

import { config as loadDotenv } from "dotenv";
import path from "path";

// Load .env from the project root, silently ignoring if absent in production.
loadDotenv({ path: path.resolve(process.cwd(), ".env") });

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function requireEnv(key: string): string {
  const value = process.env[key];
  if (!value) {
    throw new Error(`Missing required environment variable: ${key}`);
  }
  return value;
}

function optionalEnv(key: string, defaultValue: string): string {
  return process.env[key] ?? defaultValue;
}

// ---------------------------------------------------------------------------
// Config object
// ---------------------------------------------------------------------------

export interface SchemaForgeConfig {
  /** Application environment */
  env: "development" | "test" | "production";
  /** Log level */
  logLevel: "debug" | "info" | "warn" | "error";

  // ── LLM integration (NOT YET IMPLEMENTED – placeholder for TrueForge) ──
  /** Google AI / Gemini API key – required for LLM-powered analysis */
  googleApiKey: string | undefined;

  // ── Database connectivity (NOT YET IMPLEMENTED in this version) ──
  /** Database URL – required for live DB analysis */
  databaseUrl: string | undefined;

  // ── MCP server (NOT YET IMPLEMENTED) ──
  /** MCP server base URL */
  mcpServerUrl: string | undefined;
}

function loadConfig(): SchemaForgeConfig {
  const rawEnv = optionalEnv("NODE_ENV", "development");
  const env = (["development", "test", "production"].includes(rawEnv)
    ? rawEnv
    : "development") as SchemaForgeConfig["env"];

  const rawLogLevel = optionalEnv("LOG_LEVEL", "info");
  const logLevel = (["debug", "info", "warn", "error"].includes(rawLogLevel)
    ? rawLogLevel
    : "info") as SchemaForgeConfig["logLevel"];

  return {
    env,
    logLevel,
    // Optional – no throw in bootstrap; individual features will validate at use-time.
    googleApiKey: process.env["GOOGLE_API_KEY"],
    databaseUrl: process.env["DATABASE_URL"],
    mcpServerUrl: process.env["MCP_SERVER_URL"],
  };
}

/** Singleton config – loaded once at module import time. */
export const config: SchemaForgeConfig = loadConfig();

// Re-export requireEnv for modules that need to assert env vars at use-time.
export { requireEnv };
