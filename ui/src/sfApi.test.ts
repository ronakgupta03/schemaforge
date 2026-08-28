import { describe, it, expect, vi } from "vitest";
import {
  listSessions, activeSchemaForgeSession, listTurns, listEvents, downloadArtifact,
} from "./sfApi";

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

describe("listSessions", () => {
  it("returns the data array and calls the right path", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ data: [{ id: "s1", agent: { type: "reference", id: "a1", name: "schemaforge" }, title: "t", created_at: "", updated_at: "" }] }));
    const sessions = await listSessions(fetch);
    expect(sessions).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/sessions");
  });
});

describe("activeSchemaForgeSession", () => {
  it("picks the newest updated_at among schemaforge sessions only", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ data: [
      { id: "old", agent: { type: "reference", id: "a1", name: "schemaforge" }, title: "x", created_at: "", updated_at: "2026-08-28T10:00:00Z" },
      { id: "new", agent: { type: "reference", id: "a1", name: "schemaforge" }, title: "y", created_at: "", updated_at: "2026-08-28T11:00:00Z" },
      { id: "other", agent: { type: "reference", id: "a2", name: "misc" }, title: "z", created_at: "", updated_at: "2026-08-28T12:00:00Z" },
    ] }));
    expect((await activeSchemaForgeSession(fetch))?.id).toBe("new");
  });
  it("returns null when no schemaforge session exists", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ data: [] }));
    expect(await activeSchemaForgeSession(fetch)).toBeNull();
  });
});

describe("listTurns", () => {
  it("hits the session-scoped turns endpoint", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ data: [{ id: "t1" }] }));
    await listTurns(fetch, "s1");
    expect(fetch).toHaveBeenCalledWith("/api/v1/sessions/s1/turns");
  });
});

describe("listEvents", () => {
  it("returns the flat array unchanged", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse([{ type: "tool.response", id: "e1", turn_id: "t1", thread_id: "main" }]));
    const events = await listEvents(fetch, "s1", "t1");
    expect(events[0].type).toBe("tool.response");
    expect(fetch).toHaveBeenCalledWith("/api/v1/sessions/s1/turns/t1/events");
  });
});

describe("downloadArtifact", () => {
  const textResponse = (status: number, text = "") => ({ ok: status < 400, status, text: async () => text, json: async () => ({}) }) as Response;
  it("maps 200 to ok with content", async () => {
    const fetch = vi.fn().mockResolvedValue(textResponse(200, "graph LR"));
    expect(await downloadArtifact(fetch, "s1", "t1", "/workspace/out/graph.mmd"))
      .toEqual({ status: "ok", text: "graph LR" });
  });
  it("maps 404 to pending (file not written yet)", async () => {
    const fetch = vi.fn().mockResolvedValue(textResponse(404));
    expect(await downloadArtifact(fetch, "s1", "t1", "/workspace/out/graph.mmd"))
      .toEqual({ status: "pending" });
  });
  it("maps 410/412 to gone (sandbox destroyed)", async () => {
    for (const status of [410, 412]) {
      const fetch = vi.fn().mockResolvedValue(textResponse(status));
      expect((await downloadArtifact(fetch, "s1", "t1", "/workspace/out/graph.mmd")).status).toBe("gone");
    }
  });
});
