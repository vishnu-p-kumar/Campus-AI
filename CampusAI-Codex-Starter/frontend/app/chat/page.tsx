"use client";

import { FormEvent, useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../lib/api";

type Citation = { citation: number; source_type?: "document" | "web" | "company_record" | "application_record" | "drive_record"; document_id?: number; company_id?: number; title: string; filename?: string | null; version?: number; page?: number | null; section?: string | null; effective_date?: string | null; status?: string; url?: string };
type Message = { role: "user" | "assistant"; content: string; citations?: Citation[] };

function ChatContent() {
  const { api } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [language, setLanguage] = useState("en");
  const [history, setHistory] = useState<{ id: number; title: string }[]>([]);
  const [conversationId, setConversationId] = useState<number | undefined>();
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api<{ id: number; title: string }[]>("/api/v1/chat/conversations").then(setHistory).catch(() => undefined); }, [api]);
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy) return;
    const current = question.trim(); setQuestion(""); setError(""); setMessages((items) => [...items, { role: "user", content: current }]); setBusy(true);
    try {
      const response = await api<{ conversation_id: number; answer: string; citations: Citation[] }>("/api/v1/chat/", { method: "POST", body: JSON.stringify({ question: current, conversation_id: conversationId, language }) });
      setConversationId(response.conversation_id);
      setMessages((items) => [...items, { role: "assistant", content: response.answer, citations: response.citations }]);
      setHistory((items) => items.some((row) => row.id === response.conversation_id) ? items : [{ id: response.conversation_id, title: current }, ...items]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Chat request failed"); }
    finally { setBusy(false); }
  }
  async function openConversation(id: number) {
    setError("");
    try { const rows = await api<Array<{ role: "user" | "assistant"; content: string; citations: Citation[]; confidence: number }>>(`/api/v1/chat/conversations/${id}`); setConversationId(id); setMessages(rows); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load conversation"); }
  }
  async function deleteConversation(id: number) {
    setError(""); setDeletingId(id);
    try {
      await api<void>(`/api/v1/chat/conversations/${id}`, { method: "DELETE" });
      setHistory((items) => items.filter((item) => item.id !== id));
      if (conversationId === id) { setConversationId(undefined); setMessages([]); }
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not delete conversation"); }
    finally { setDeletingId(null); }
  }
  return <div className="chat-layout">
    <aside className="panel chat-history"><div className="section-heading"><h2>Conversations</h2><button className="text-button" onClick={() => { setConversationId(undefined); setMessages([]); }}>New</button></div>
      {history.map((item) => <div className={`history-item ${conversationId === item.id ? "selected" : ""}`} key={item.id}><button className="history-open" onClick={() => openConversation(item.id)}>{item.title}</button><button className="history-delete" aria-label={`Delete conversation: ${item.title}`} title="Delete conversation and messages" disabled={deletingId === item.id} onClick={() => deleteConversation(item.id)}>{deletingId === item.id ? "…" : "Delete"}</button></div>)}
      {!history.length && <p className="muted small-note">Your saved chats will appear here.</p>}
    </aside>
    <section className="panel chat-panel"><div className="page-heading"><div><p className="eyebrow">DOCUMENT-GROUNDED ASSISTANT</p><h1>Ask CampusAI</h1><p className="muted">Answers use admin-approved placement documents and show their citations. Authorized website sources are used only when configured; otherwise unsupported questions are declined.</p></div>
      <label className="language-select">Answer language<select value={language} onChange={(e) => setLanguage(e.target.value)}><option value="en">English</option><option value="hi">हिन्दी</option><option value="kn">ಕನ್ನಡ</option></select></label>
    </div>
      <div className="chat-messages" aria-live="polite">{messages.length === 0 && <div className="empty-state"><strong>Try a placement question</strong><p>For example: “What CGPA is required for the current placement policy?”</p></div>}
        {messages.map((message, index) => <article className={`chat-message message-${message.role}`} key={`${index}-${message.role}`}><strong>{message.role === "user" ? "You" : "CampusAI"}</strong><p>{message.content}</p>{message.citations?.length ? <div className="citation-list"><strong>Sources</strong>{message.citations.map((source) => <span key={`${source.url ?? source.document_id}-${source.citation}`}>[{source.citation}] {source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a> : <>{source.title}{source.filename && source.filename !== source.title ? ` · ${source.filename}` : ""}{source.version ? `, v${source.version}` : ""}{source.page ? `, p. ${source.page}` : ""}{source.section ? `, section: ${source.section}` : ""}{source.status === "superseded" ? " · historical version" : ""}</>}</span>)}</div> : null}</article>)}
        {busy && <div className="loading-panel">Searching approved documents and preparing a cited response…</div>}
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      <form className="chat-composer" onSubmit={send}><textarea required minLength={3} maxLength={3000} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about policy, eligibility, drives, or placement steps…" /><button className="button button-primary" disabled={busy || question.trim().length < 3}>{busy ? "Working…" : "Send"}</button></form>
    </section>
  </div>;
}

export default function ChatPage() { return <RequireAuth><ChatContent /></RequireAuth>; }
