/**
 * SchemaForge – SchemaForgeError
 *
 * Typed error hierarchy used throughout the codebase.
 * Always throw a SchemaForgeError (or a subclass) instead of a plain Error
 * so callers can distinguish domain errors from unexpected failures.
 */

export type ErrorCode =
  | "VALIDATION_ERROR"
  | "CONFIG_MISSING"
  | "DB_ANALYSIS_FAILED"
  | "AST_ANALYSIS_FAILED"
  | "PLAN_GENERATION_FAILED"
  | "SAFETY_CHECK_FAILED"
  | "APPROVAL_REQUIRED"
  | "NOT_IMPLEMENTED"
  | "UNKNOWN";

export class SchemaForgeError extends Error {
  public readonly code: ErrorCode;
  public readonly context: Record<string, unknown>;

  constructor(
    message: string,
    code: ErrorCode = "UNKNOWN",
    context: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "SchemaForgeError";
    this.code = code;
    this.context = context;
    // Maintains proper prototype chain in transpiled ES5
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/** Thrown when a feature is defined but not yet implemented. */
export class NotImplementedError extends SchemaForgeError {
  constructor(feature: string) {
    super(`Not yet implemented: ${feature}`, "NOT_IMPLEMENTED", { feature });
    this.name = "NotImplementedError";
  }
}

/** Thrown when a Zod schema parse fails on external input. */
export class ValidationError extends SchemaForgeError {
  constructor(message: string, context: Record<string, unknown> = {}) {
    super(message, "VALIDATION_ERROR", context);
    this.name = "ValidationError";
  }
}
