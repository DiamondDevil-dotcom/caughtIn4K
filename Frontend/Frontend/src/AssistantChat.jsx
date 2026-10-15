import { useEffect, useRef, useState } from "react";

export default function AssistantChat({ cloud }) {
  const [message, setMessage] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [turns, setTurns] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  async function send(event) {
    event.preventDefault();
    const question = message.trim();
    if (!agreed || !question || pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await cloud.request("POST", "/cloud/assistant/chat", { message: question });
      if (typeof result.reply !== "string" || !result.reply.trim()) throw new Error("AI help returned an invalid reply.");
      if (!active.current) return;
      setTurns(previous => [...previous, { question, reply: result.reply }].slice(-10));
      setMessage("");
    } catch (failure) {
      if (active.current) setError(failure.message);
    } finally {
      pending.current = false;
      if (active.current) setBusy(false);
    }
  }

  return <details className="customer-panel">
    <summary>AI setup and security help</summary>
    <p>General guidance only: no live device access or actions. Each question is independent; earlier messages are not sent. AI can make mistakes.</p>
    <label><input type="checkbox" checked={agreed} disabled={busy} onChange={event => setAgreed(event.target.checked)} />
      I agree to send my typed question to OpenAI. Do not include passwords, QR codes, credentials or private network data.
    </label>
    <div role="log" aria-label="AI help conversation">
      {turns.map((turn, index) => <div key={index}>
        <p><strong>You:</strong> {turn.question}</p>
        <p style={{ whiteSpace: "pre-wrap" }}><strong>AI:</strong> {turn.reply}</p>
      </div>)}
    </div>
    <form onSubmit={send}>
      <label>Your question<textarea value={message} maxLength={2000} disabled={busy}
        onChange={event => setMessage(event.target.value)} required /></label>
      <button disabled={busy || !agreed || !message.trim()}>{busy ? "Asking..." : "Ask AI"}</button>
      <button type="button" disabled={busy} onClick={() => { setTurns([]); setMessage(""); setError(""); }}>Clear chat</button>
    </form>
    {error && <p role="alert">{error}</p>}
    <small>Chat is kept only while this panel is mounted, not saved by this app.</small>
  </details>;
}
