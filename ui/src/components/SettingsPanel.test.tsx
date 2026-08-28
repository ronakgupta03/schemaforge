// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import * as matchers from "@testing-library/jest-dom/matchers";
import { test, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { SettingsPanel } from "./SettingsPanel";

expect.extend(matchers);

afterEach(() => {
  cleanup();
});

const ok = (body: unknown) => ({ ok: true, json: async () => body }) as Response;

function mockFetch(overrides: Record<string, () => Promise<Response>>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    for (const [prefix, fn] of Object.entries(overrides)) {
      if (url.startsWith(prefix)) return fn();
    }
    return ok({ data: [] });
  });
}

test("renders five sections and live status", async () => {
  const fetchFn = mockFetch({
    "/api/v1/settings/mcp-servers": async () => ok({ data: [{ name: "github", url: "http://y/mcp" }] }),
    "/api/v1/models": async () => ok({ data: [{ name: "cloudflare/deepseek-v4-flash" }] }),
    "/api/v1/capabilities": async () => ok({ data: { sandbox: { enabled: true } } }),
    "/api/sf/snapshot": async () => ok({ data: { mcp_servers: [{ name: "github" }], models: ["cloudflare/deepseek-v4-flash"], sandbox_enabled: true } }),
  });
  render(<SettingsPanel fetchFn={fetchFn} />);
  expect(await screen.findByText("Models")).toBeInTheDocument();
  expect(screen.getByText("Connectors")).toBeInTheDocument();
  expect(screen.getByText("Services")).toBeInTheDocument();
  expect(screen.getByText("Sandbox")).toBeInTheDocument();
  expect(screen.getByText("Apply agent")).toBeInTheDocument();
  expect(screen.getByText("cloudflare/deepseek-v4-flash")).toBeInTheDocument();
});

test("Apply button posts to the registry and shows the manifest", async () => {
  const fetchFn = mockFetch({
    "/api/sf/apply-agent": async () => ok({ data: { manifest: { model: { name: "x" } }, omitted: [] } }),
  });
  render(<SettingsPanel fetchFn={fetchFn} />);
  fireEvent.click(await screen.findByText("Save & apply agent"));
  expect(await screen.findByText(/manifest applied/i)).toBeInTheDocument();
});
