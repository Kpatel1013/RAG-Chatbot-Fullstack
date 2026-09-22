import { useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");
const ACCEPT = ".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.gif";

type Message = { id: string; role: "user" | "assistant"; content: string };
type Conversation = { id: string; title: string };
type Attachment = { name: string; docId?: string; preview?: string };

async function api(path: string, init?: RequestInit) {
  const res = await fetch(`${API}${path}`, init);

  if (!res.ok && res.status !== 204) {
    throw new Error(await res.text());
  }

  if (res.status === 204) {
    return null;
  }

  return res.json();
}

function isAllowedFile(file: File): boolean {
  if (file.type.startsWith("image/")) {
    return true;
  }

  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  return ACCEPT.includes(ext);
}

function fileFromPaste(clipboard: DataTransfer | null): File | null {
  if (!clipboard) {
    return null;
  }

  for (const item of clipboard.items) {
    if (item.kind !== "file") {
      continue;
    }

    const file = item.getAsFile();
    if (file && isAllowedFile(file)) {
      return file;
    }
  }

  for (const file of clipboard.files) {
    if (isAllowedFile(file)) {
      return file;
    }
  }

  return null;
}

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attachment, setAttachment] = useState<Attachment | null>(null);

  const fileInput = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const isEmpty = messages.length === 0 && !busy;
  const canSend =
    Boolean(input.trim()) && !busy && !uploading && !(attachment && !attachment.docId);

  function clearAttachment() {
    if (attachment?.preview) {
      URL.revokeObjectURL(attachment.preview);
    }
    setAttachment(null);
  }

  // Load conversation list once on start
  useEffect(() => {
    api("/api/conversations")
      .then(setConversations)
      .catch(() => setError("Could not load conversations"));
  }, []);

  // Load messages when the active chat changes
  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }

    api(`/api/conversations/${activeId}/messages`)
      .then(setMessages)
      .catch(() => setError("Could not load messages"));
  }, [activeId]);

  // Keep the latest message in view
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  // Grow the textarea as the user types
  useEffect(() => {
    const el = composerRef.current;
    if (!el) {
      return;
    }

    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [input, isEmpty]);

  async function upload(file: File) {
    setUploading(true);
    setError(null);

    const preview = file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined;

    setAttachment({ name: file.name, preview });

    const form = new FormData();
    form.append("file", file);

    try {
      const data = await api("/api/upload", { method: "POST", body: form });
      setAttachment({
        name: data.filename ?? file.name,
        docId: data.doc_id,
        preview,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
      setAttachment(null);
    } finally {
      setUploading(false);
      if (fileInput.current) {
        fileInput.current.value = "";
      }
    }
  }

  function handlePaste(e: React.ClipboardEvent) {
    const file = fileFromPaste(e.clipboardData);
    if (!file) {
      return;
    }

    e.preventDefault();
    void upload(file);
  }

  async function send() {
    const text = input.trim();
    if (!canSend || !text) {
      return;
    }

    setInput("");
    setBusy(true);
    setError(null);

    // Show the user message right away while we wait for the reply
    const localId = `local-${Date.now()}`;
    setMessages((prev) => [...prev, { id: localId, role: "user", content: text }]);

    try {
      const data = await api("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: activeId,
          message: text,
          doc_id: attachment?.docId ?? null,
        }),
      });

      setActiveId(data.conversation_id);

      const msgs = await api(`/api/conversations/${data.conversation_id}/messages`);
      const convs = await api("/api/conversations");

      setMessages(msgs);
      setConversations(convs);
      clearAttachment();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Send failed");
      setMessages((prev) => prev.filter((m) => m.id !== localId));
    } finally {
      setBusy(false);
    }
  }

  async function deleteChat(id: string, e: React.MouseEvent) {
    e.stopPropagation();

    try {
      await api(`/api/conversations/${id}`, { method: "DELETE" });
    } catch {
      setError("Could not delete conversation");
      return;
    }

    setConversations((rows) => rows.filter((c) => c.id !== id));

    if (activeId === id) {
      setActiveId(null);
      setMessages([]);
      clearAttachment();
    }
  }

  function newChat() {
    setActiveId(null);
    setMessages([]);
    setError(null);
    clearAttachment();
    composerRef.current?.focus();
  }

  function openConversation(id: string) {
    setActiveId(id);
    clearAttachment();
    setError(null);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  const composer = (
    <form
      className={uploading ? "composer busy" : "composer"}
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
      onPaste={handlePaste}
    >
      <input
        ref={fileInput}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            void upload(file);
          }
        }}
      />

      {attachment && (
        <div className="attach-chip">
          {attachment.preview ? (
            <img src={attachment.preview} alt="" />
          ) : (
            <span>{attachment.name}</span>
          )}
          <span>{uploading ? "Reading…" : attachment.name}</span>
          <button
            type="button"
            className="attach-clear"
            onClick={clearAttachment}
            aria-label="Remove attachment"
          >
            ×
          </button>
        </div>
      )}

      <textarea
        ref={composerRef}
        rows={1}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask anything"
        disabled={busy}
      />

      <div className="composer-bar">
        <button
          type="button"
          className="icon-btn"
          disabled={uploading || busy}
          onClick={() => fileInput.current?.click()}
          aria-label="Upload"
        >
          +
        </button>
        <button type="submit" className="send-btn" disabled={!canSend} aria-label="Send">
          ↑
        </button>
      </div>
    </form>
  );

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">RAG Chat</div>

        <button type="button" className="new-chat" onClick={newChat}>
          + New chat
        </button>

        <div className="conv-list">
          {conversations.length === 0 && <p className="muted">No conversations yet</p>}

          {conversations.map((c) => (
            <div key={c.id} className={c.id === activeId ? "conv-row active" : "conv-row"}>
              <button type="button" className="conv" onClick={() => openConversation(c.id)}>
                {c.title}
              </button>
              <button
                type="button"
                className="conv-delete"
                onClick={(e) => deleteChat(c.id, e)}
                aria-label={`Delete ${c.title}`}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </aside>

      <main className="main">
        {error && <div className="error">{error}</div>}

        {isEmpty ? (
          <div className="hero">
            <h1>Hi. What&apos;s on your mind today?</h1>
            {composer}
            <p className="hint">Paste a screenshot here, or attach a file below the box.</p>
          </div>
        ) : (
          <>
            <div className="messages">
              {messages.map((m) => (
                <div key={m.id} className={`bubble ${m.role}`}>
                  <p>{m.content}</p>
                </div>
              ))}

              {busy && (
                <div className="bubble assistant typing" aria-label="Loading">
                  <span className="dot" />
                  <span className="dot" />
                  <span className="dot" />
                </div>
              )}

              <div ref={bottom} />
            </div>

            <div className="dock">{composer}</div>
          </>
        )}
      </main>
    </div>
  );
}
