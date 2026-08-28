import { EvidencePanel } from "./components/EvidencePanel";

// The chat is the TrueForge server's own UI (the npm @truefoundry/trueforge-ui
// SDK crashes in this build environment with a tap getSnapshot loop — verified
// across React 18/19, dev/prod, and all dedupe configs; the server's bundled
// build works). Embedding it keeps the full product chat: streaming, approvals,
// session history.
// Local dev: [::1]:8790 (harness binds IPv6 loopback only).
// Production: same-origin route serving the TrueForge UI (see deploy/).
const CHAT_URL = import.meta.env.VITE_CHAT_URL ?? (import.meta.env.DEV ? "http://[::1]:8790" : "/");

export default function App() {
  return (
    <div className="flex h-dvh w-full">
      <div className="h-full w-[55%] min-w-0 border-r" style={{ borderColor: "var(--sf-border)" }}>
        <iframe
          src={CHAT_URL}
          title="TrueForge"
          className="h-full w-full border-0"
        />
      </div>
      <div className="h-full flex-1 min-w-0">
        <EvidencePanel />
      </div>
    </div>
  );
}