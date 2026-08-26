/**
 * SchemaForge – Logger
 *
 * Minimal structured logger built on the Node.js built-in console.
 * Outputs JSON lines in non-development environments, human-readable
 * colourised text in development.
 *
 * Usage:
 *   import { logger } from "./logger";
 *   logger.info("Starting analysis", { requestId: "..." });
 */

import { config } from "./config";

export type LogLevel = "debug" | "info" | "warn" | "error";

const LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

function shouldLog(level: LogLevel): boolean {
  return LEVELS[level] >= LEVELS[config.logLevel];
}

function formatDev(level: LogLevel, message: string, meta?: Record<string, unknown>): string {
  const ts = new Date().toISOString();
  const prefix = `[${ts}] ${level.toUpperCase().padEnd(5)}`;
  const metaStr = meta && Object.keys(meta).length > 0 ? ` ${JSON.stringify(meta)}` : "";
  return `${prefix} ${message}${metaStr}`;
}

function formatJson(level: LogLevel, message: string, meta?: Record<string, unknown>): string {
  return JSON.stringify({
    timestamp: new Date().toISOString(),
    level,
    message,
    ...meta,
  });
}

function log(level: LogLevel, message: string, meta?: Record<string, unknown>): void {
  if (!shouldLog(level)) return;

  const line =
    config.env === "development"
      ? formatDev(level, message, meta)
      : formatJson(level, message, meta);

  if (level === "error") {
    console.error(line);
  } else if (level === "warn") {
    console.warn(line);
  } else {
    console.log(line);
  }
}

export const logger = {
  debug: (message: string, meta?: Record<string, unknown>): void => log("debug", message, meta),
  info: (message: string, meta?: Record<string, unknown>): void => log("info", message, meta),
  warn: (message: string, meta?: Record<string, unknown>): void => log("warn", message, meta),
  error: (message: string, meta?: Record<string, unknown>): void => log("error", message, meta),
} as const;
