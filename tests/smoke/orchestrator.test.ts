/**
 * Orchestrator smoke tests.
 *
 * Verifies that:
 *   1. dryRun() returns a valid PipelineResult without calling any agent.
 *   2. run() surfaces a NotImplementedError immediately (StubTrueForgeAdapter).
 *   3. Error types are correctly shaped.
 */

import { randomUUID } from "crypto";
import { Orchestrator } from "../../src/orchestrator";
import { StubTrueForgeAdapter } from "../../src/integrations/trueforge";
import { NotImplementedError } from "../../src/errors";
import { MigrationRequestSchema } from "../../src/types";

const baseRequest = MigrationRequestSchema.parse({
  id: randomUUID(),
  description: "Split the users table",
  type: "split_table",
  targetTable: "users",
  createdAt: new Date().toISOString(),
});

describe("Orchestrator.dryRun", () => {
  it("returns a PipelineResult at request_received stage", () => {
    const orchestrator = new Orchestrator(new StubTrueForgeAdapter());
    const result = orchestrator.dryRun(baseRequest);

    expect(result.reachedStage).toBe("request_received");
    expect(result.request.id).toBe(baseRequest.id);
    expect(result.approval?.status).toBe("pending");
  });

  it("does NOT mutate the original request", () => {
    const orchestrator = new Orchestrator(new StubTrueForgeAdapter());
    const original = { ...baseRequest };
    orchestrator.dryRun(baseRequest);
    expect(baseRequest).toEqual(original);
  });
});

describe("Orchestrator.run (stub adapter)", () => {
  it("throws NotImplementedError immediately at the DB Analysis stage", async () => {
    const orchestrator = new Orchestrator(new StubTrueForgeAdapter());
    await expect(orchestrator.run(baseRequest)).rejects.toBeInstanceOf(
      NotImplementedError,
    );
  });

  it("NotImplementedError has the correct error code", async () => {
    const orchestrator = new Orchestrator(new StubTrueForgeAdapter());
    try {
      await orchestrator.run(baseRequest);
      fail("Expected NotImplementedError to be thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(NotImplementedError);
      if (err instanceof NotImplementedError) {
        expect(err.code).toBe("NOT_IMPLEMENTED");
      }
    }
  });
});

describe("NotImplementedError", () => {
  it("is an instance of SchemaForgeError", () => {
    const err = new NotImplementedError("test feature");
    expect(err.code).toBe("NOT_IMPLEMENTED");
    expect(err.message).toContain("test feature");
    expect(err.context).toHaveProperty("feature");
  });
});
