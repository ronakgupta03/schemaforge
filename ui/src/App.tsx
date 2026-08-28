import {
  TrueForgeUI,
  type TrueForgeServerConfig,
  type ThemeConfig,
} from "@truefoundry/trueforge-ui";
import { EvidencePanel } from "./components/EvidencePanel";

// Step 2: createTrueFoundryServer is confirmed exported from @truefoundry/trueforge-ui (dist/index.js).
// For connecting to the local TrueForge harness, TrueForgeServerConfig uses the built-in "trueforge" adapter.
const server: TrueForgeServerConfig = { type: "trueforge", baseUrl: "/" };
const theme: ThemeConfig = {
  preset: "trueforge",
  mode: "dark",
  tokens: {
    primaryBg: "#0b1220",
    secondaryBg: "#101a2e",
    border: "#1e2a44",
    textPrimary: "#e2e8f0",
    textSecondary: "#94a3b8",
    primaryButtonBg: "#38bdf8",
    radius: "0.5rem",
  },
};

export default function App() {
  return (
    <div className="flex h-dvh w-full">
      <div className="h-full w-[55%] min-w-0 border-r" style={{ borderColor: "var(--sf-border)" }}>
        <TrueForgeUI
          server={server}
          layout="sidebar"
          agentConfig={{ mode: "SingleAgent", name: "schemaforge" }}
          theme={theme}
          className="h-full"
        />
      </div>
      <div className="h-full flex-1 min-w-0">
        <EvidencePanel />
      </div>
    </div>
  );
}
