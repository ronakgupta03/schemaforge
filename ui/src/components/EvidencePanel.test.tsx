// @vitest-environment jsdom
import { it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EvidencePanel } from "./EvidencePanel";
import * as useEvidenceModule from "../hooks/useEvidence";
import type { EvidenceState } from "../hooks/useEvidence";

const baseState: EvidenceState = {
  session: { id: "s1", agent: { type: "reference", id: "a1", name: "schemaforge" }, title: "t", created_at: "", updated_at: "" },
  turn: { id: "t1", session_id: "s1", previous_turn_id: null, input: {}, state: { status: "running" }, created_at: "" },
  artifacts: {},
  activity: [],
  phase: "running",
  approvalPending: false,
  loaded: true,
};

beforeEach(() => {
  vi.restoreAllMocks();
});

it("resets visited review state on second approval gate and turn change", () => {
  let mockState: EvidenceState = { ...baseState, approvalPending: true, phase: "paused" };
  vi.spyOn(useEvidenceModule, "useEvidence").mockImplementation(() => mockState);

  const { rerender } = render(<EvidencePanel />);

  // Initially on approval gate, Report should have unreviewed dot 'Report ●'
  expect(screen.getByText("Report ●")).toBeDefined();

  // Review the Report tab
  fireEvent.click(screen.getByText("Report ●"));
  expect(screen.queryByText("Report ●")).toBeNull();
  expect(screen.getByText("Report")).toBeDefined();

  // Approval finishes (approvalPending becomes false)
  mockState = { ...baseState, approvalPending: false, phase: "running" };
  rerender(<EvidencePanel />);
  expect(screen.queryByText("Report ●")).toBeNull();

  // Second approval gate triggers (approvalPending transitions false -> true)
  mockState = { ...baseState, approvalPending: true, phase: "paused" };
  rerender(<EvidencePanel />);
  // Report should glow / show unreviewed dot again
  expect(screen.getByText("Report ●")).toBeDefined();

  // Review Report again
  fireEvent.click(screen.getByText("Report ●"));
  expect(screen.queryByText("Report ●")).toBeNull();

  // Turn changes to t2 (still approval pending)
  mockState = {
    ...baseState,
    turn: { id: "t2", session_id: "s1", previous_turn_id: "t1", input: {}, state: { status: "paused" }, created_at: "" },
    approvalPending: true,
    phase: "paused",
  };
  rerender(<EvidencePanel />);
  // Report should be unreviewed again because turn changed
  expect(screen.getByText("Report ●")).toBeDefined();
});
