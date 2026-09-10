import { useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");

type Message = { id: string; role: "user" | "assistant"; content: string; createdAt: string };
type Conversation = { id: string; title: string; updatedAt: string };

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${API}/api/conversations`)
      .then((r) => r.json())
      .then(setConversations)
      .catch(() => setError("Could not load conversations"));
  }, []);

  useEffect(() => {
    if (!activeId) return setMessages([]);
    fetch(`${API}/api/conversations/${activeId}/messages`)
      .then((r) => r.json())
      .then(setMessages)
      .catch(() => setError("Could not load messages"));
  }, [activeId]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    setStatus(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(`${API}/api/upload`, { method: "POST", body: form });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setStatus(data.message);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setError(null);

    try {
      const res = await fetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: activeId, message: text }),
      });
      if (!res.ok) throw new Error(await res.text());

      const data = await res.json();
      setActiveId(data.conversation_id);

      const [msgs, convs] = await Promise.all([
        fetch(`${API}/api/conversations/${data.conversation_id}/messages`).then((r) => r.json()),
        fetch(`${API}/api/conversations`).then((r) => r.json()),
      ]);
      setMessages(msgs);
      setConversations(convs);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Send failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>RAG Chatbot</h1>

        <button type="button" onClick={() => { setActiveId(null); setMessages([]); setError(null); }}>
          + New Chat
        </button>

        <input
          ref={fileInput}
          type="file"
          accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.gif"
          hidden
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
        />
        <button type="button" className="upload-btn" disabled={uploading || busy} onClick={() => fileInput.current?.click()}>
          {uploading ? "Uploading..." : "Upload PDF / Photo"}
        </button>

        {status && <p className="status-ok">{status}</p>}
        {conversations.length === 0 && <p className="muted">No conversations yet</p>}
        {conversations.map((c) => (
          <button key={c.id} type="button" className={c.id === activeId ? "conv active" : "conv"} onClick={() => setActiveId(c.id)}>
            {c.title}
          </button>
        ))}
      </aside>

      <main className="main">
        {error && <div className="error">{error}</div>}

        <div className="messages">
          {messages.length === 0 && !busy && (
            <div className="empty">
              <h2>Start a conversation</h2>
              <p>Upload a PDF or photo, then ask questions about it.</p>
            </div>
          )}
          {messages.map((m) => (
            <div key={m.id} className={`bubble ${m.role}`}>
              <strong>{m.role === "user" ? "You" : "Assistant"}</strong>
              <p>{m.content}</p>
            </div>
          ))}
          {busy && <div className="bubble assistant typing">Thinking...</div>}
          <div ref={bottom} />
        </div>

        <form className="input-row" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask a question..." disabled={busy} />
          <button type="submit" disabled={busy || !input.trim()}>{busy ? "..." : "Send"}</button>
        </form>
      </main>
    </div>
  );
}
