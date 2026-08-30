// SchemaForge Evidence UI: full TrueForge native chat.
// The separate side panel is removed; the bundled TrueForge UI (forked/patched
// with native Impact/Report/Changes/Verification/Activity tabs) is served from
// the same origin via the /tf/* proxy to the TrueForge server at :8790.
const CHAT_URL = import.meta.env.VITE_CHAT_URL ?? "/tf/";

export default function App() {
  return (
    <div className="h-dvh w-full">
      <iframe
        src={CHAT_URL}
        title="TrueForge"
        className="h-full w-full border-0"
      />
    </div>
  );
}
