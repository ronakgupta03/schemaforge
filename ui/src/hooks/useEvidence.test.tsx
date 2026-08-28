// @vitest-environment jsdom
import { it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useEvidence, ARTIFACT_PATHS } from "./useEvidence";
import * as sf from "../sfApi";

const session = { id: "s1", agent: { type: "reference", id: "a1", name: "schemaforge" }, title: "t", created_at: "", updated_at: "2026-08-28T11:00:00Z" };
const runningTurn = { id: "t1", session_id: "s1", previous_turn_id: null, input: {}, state: { status: "running" }, created_at: "" };
const pausedTurn = { ...runningTurn, state: { status: "done", required_actions: [{ type: "tool.approval_required" }] } };

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
