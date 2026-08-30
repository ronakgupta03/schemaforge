// SchemaForge Evidence UI: full TrueForge native chat.
// The left pane is removed; TrueForge UI SDK renders artifacts
// (Impact/Report/Changes/Verification/Activity) itself as native tabs.
const CHAT_URL = import.meta.env.VITE_CHAT_URL ?? (import.meta.env.DEV ? "http://[::1]:8790" : "/tf/");

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
