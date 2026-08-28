// @vitest-environment jsdom
import { it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useEvidence, ARTIFACT_PATHS } from "./useEvidence";
import * as sf from "../sfApi";

const session = { id: "s1", agent: { type: "reference", id: "a1", name: "schemaforge" }, title: "t", created_at: "", updated_at: "2026-08-28T11:00:00Z" };
const runningTurn: sf.Turn = { id: "t1", session_id: "s1", previous_turn_id: null, input: {}, state: { status: "running" }, created_at: "" };
const pausedTurn: sf.Turn = { ...runningTurn, state: { status: "done", required_actions: [{ type: "tool.approval_required" }] } };

beforeEach(() => { vi.restoreAllMocks(); });

it("polls until artifacts are fetched once each", async () => {
  vi.spyOn(sf, "listSessions").mockResolvedValue([session]);
  vi.spyOn(sf, "listTurns").mockResolvedValue([runningTurn]);
  vi.spyOn(sf, "listEvents").mockResolvedValue([]);
  vi.spyOn(sf, "downloadArtifact").mockImplementation(async (_f, _s, _t, path) =>
    path === ARTIFACT_PATHS.graph ? { status: "ok", text: "graph LR" } : { status: "pending" });

  const { result } = renderHook(() => useEvidence(10));
  await waitFor(() => expect(result.current.loaded).toBe(true));
  expect(result.current.session?.id).toBe("s1");
  expect(result.current.artifacts.graph).toBe("graph LR");
  expect(sf.downloadArtifact).toHaveBeenCalledWith(expect.anything(), "s1", "t1", ARTIFACT_PATHS.graph);
});

it("marks approvalPending when the turn is paused on a tool approval", async () => {
  vi.spyOn(sf, "listSessions").mockResolvedValue([session]);
  vi.spyOn(sf, "listTurns").mockResolvedValue([pausedTurn]);
  vi.spyOn(sf, "listEvents").mockResolvedValue([]);
  vi.spyOn(sf, "downloadArtifact").mockResolvedValue({ status: "pending" });

  const { result } = renderHook(() => useEvidence(10));
  await waitFor(() => expect(result.current.phase).toBe("paused"));
  expect(result.current.approvalPending).toBe(true);
});

it("resets artifacts and activity when the turn changes", async () => {
  const turn1: sf.Turn = { id: "t1", session_id: "s1", previous_turn_id: null, input: {}, state: { status: "running" }, created_at: "" };
  const turn2: sf.Turn = { id: "t2", session_id: "s1", previous_turn_id: "t1", input: {}, state: { status: "running" }, created_at: "" };
  let currentTurn = turn1;

  vi.spyOn(sf, "listSessions").mockResolvedValue([session]);
  vi.spyOn(sf, "listTurns").mockImplementation(async () => [currentTurn]);
  vi.spyOn(sf, "listEvents").mockImplementation(async (_f, _s, turnId) =>
    turnId === "t1"
      ? [{ id: "e1", type: "message", session_id: "s1", turn_id: "t1", thread_id: null, created_at: "", data: { text: "turn 1 event" } }]
      : [{ id: "e2", type: "message", session_id: "s1", turn_id: "t2", thread_id: null, created_at: "", data: { text: "turn 2 event" } }]
  );
  vi.spyOn(sf, "downloadArtifact").mockImplementation(async (_f, _s, turnId, path) => {
    if (path === ARTIFACT_PATHS.graph) {
      return { status: "ok", text: `graph for ${turnId}` };
    }
    return { status: "pending" };
  });

  const { result } = renderHook(() => useEvidence(10));
  await waitFor(() => expect(result.current.turn?.id).toBe("t1"));
  expect(result.current.artifacts.graph).toBe("graph for t1");
  expect(result.current.activity).toHaveLength(1);
  expect(result.current.activity[0].id).toBe("e1");

  currentTurn = turn2;
  await waitFor(() => expect(result.current.turn?.id).toBe("t2"));
  expect(result.current.artifacts.graph).toBe("graph for t2");
  expect(result.current.activity).toHaveLength(1);
  expect(result.current.activity[0].id).toBe("e2");
  expect(sf.downloadArtifact).toHaveBeenCalledWith(expect.anything(), "s1", "t2", ARTIFACT_PATHS.graph);
});

it("keeps approvalPending true across multiple polls when event was seen on first poll", async () => {
  let pollCount = 0;
  vi.spyOn(sf, "listSessions").mockResolvedValue([session]);
  vi.spyOn(sf, "listTurns").mockResolvedValue([runningTurn]);
  vi.spyOn(sf, "listEvents").mockImplementation(async () => {
    pollCount++;
    return [{ id: "e_appr", type: "tool.approval_required", session_id: "s1", turn_id: "t1", thread_id: null, created_at: "", data: {} }];
  });
  vi.spyOn(sf, "downloadArtifact").mockResolvedValue({ status: "pending" });

  const { result } = renderHook(() => useEvidence(10));
  await waitFor(() => expect(pollCount).toBeGreaterThanOrEqual(2));
  expect(result.current.approvalPending).toBe(true);
});
