"use client";

import { FormEvent, useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../lib/api";

type Citation = { citation: number; source_type?: "document" | "web" | "company_record" | "notification_record" | "application_record" | "drive_record"; document_id?: number; notification_id?: number; company_id?: number; title: string; filename?: string | null; version?: number; page?: number | null; section?: string | null; effective_date?: string | null; status?: string; url?: string };
type Message = { role: "user" | "assistant"; content: string; citations?: Citation[] };
type Usage = { queries_used: number; daily_query_limit: number; queries_remaining: number; reset_date: string };
type AnswerBlock = { type: "paragraph"; text: string } | { type: "list"; items: string[] };

function structureAnswer(content: string): { heading?: string; blocks: AnswerBlock[] } {
  const lines = content.replace(/\*\*/g, "").replace(/\r/g, "").split("\n");
  const headingIndex = lines.findIndex((line) => line.trim());
  if (headingIndex < 0) return { blocks: [] };
  const firstLine = lines[headingIndex].trim();
  const markdownHeading = /^\s{0,3}#{1,6}\s+/.test(lines[headingIndex]);
  const colonHeading = /^[^:]{1,80}:$/.test(firstLine) && lines.slice(headingIndex + 1).some((line) => line.trim());
  const hasHeading = markdownHeading || colonHeading;
  const clean = (line: string) => line.replace(/^\s{0,3}#{1,6}\s+/, "").trim();
  const heading = hasHeading ? clean(lines[headingIndex]).replace(/[:：]\s*$/, "") : undefined;
  const blocks: AnswerBlock[] = [];
  let paragraph: string[] = [];
  let items: string[] = [];
  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ type: "paragraph", text: paragraph.join(" ") });
    paragraph = [];
  };
  const flushList = () => {
    if (items.length) blocks.push({ type: "list", items });
    items = [];
  };
  for (const rawLine of lines.slice(headingIndex + (hasHeading ? 1 : 0))) {
    const line = clean(rawLine);
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }
    const listItem = line.match(/^(?:[-*•]|\d+[.)])\s+(.+)$/);
    if (listItem) {
      flushParagraph();
      items.push(listItem[1]);
    } else if (/^[^:]{1,60}:\s+\S/.test(line)) {
      flushParagraph();
      flushList();
      blocks.push({ type: "paragraph", text: line });
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  return { heading, blocks };
}

function ChatContent() {
  const { api } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<{ id: number; title: string }[]>([]);
  const [conversationId, setConversationId] = useState<number | undefined>();
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [usage, setUsage] = useState<Usage | null>(null);
  useEffect(() => {
    api<{ id: number; title: string }[]>("/api/v1/chat/conversations").then(setHistory).catch(() => undefined);
    api<Usage>("/api/v1/chat/usage").then(setUsage).catch(() => undefined);
  }, [api]);
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy) return;
    const current = question.trim(); setQuestion(""); setError(""); setMessages((items) => [...items, { role: "user", content: current }]); setBusy(true);
    const controller = new AbortController();
    const requestTimeout = window.setTimeout(() => controller.abort(), 60_000);
    try {
      const response = await api<{ conversation_id: number; answer: string; citations: Citation[]; queries_used: number; daily_query_limit: number; queries_remaining: number; reset_date: string | null }>("/api/v1/chat/", { method: "POST", body: JSON.stringify({ question: current, conversation_id: conversationId }), signal: controller.signal });
      setConversationId(response.conversation_id);
      setUsage({ queries_used: response.queries_used, daily_query_limit: response.daily_query_limit, queries_remaining: response.queries_remaining, reset_date: response.reset_date ?? "" });
      setMessages((items) => [...items, { role: "assistant", content: response.answer, citations: response.citations }]);
      setHistory((items) => items.some((row) => row.id === response.conversation_id) ? items : [{ id: response.conversation_id, title: current }, ...items]);
    } catch (cause) {
      setError(cause instanceof DOMException && cause.name === "AbortError"
        ? "The assistant took too long to respond. Please try again."
        : cause instanceof Error ? cause.message : "Chat request failed");
    }
    finally { window.clearTimeout(requestTimeout); setBusy(false); }
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
    <section className="panel chat-panel"><div className="page-heading"><div><p className="eyebrow">PLACEMENT QUERY BOT</p><h1>Ask CampusAI</h1><p className="muted">Ask about placements, admin approved uploads, company profiles, and your notifications. You can ask for unread messages or a full message by its title.</p><p className="muted small-note">Student learning project; not an official BNMIT service. Some information may be outdated. <a href="mailto:vins.techn@gmail.com">Contact the project maintainer</a>.</p></div></div>
      {usage && <div className="panel"><div className="section-heading"><strong>Daily usage</strong><span>{usage.queries_used} / {usage.daily_query_limit} queries used</span></div><progress aria-label="Placement bot daily query limit" value={Math.min(usage.queries_used, usage.daily_query_limit)} max={usage.daily_query_limit} style={{ width: "100%" }} /><p className="muted small-note">{usage.queries_remaining} queries remaining · resets daily at midnight</p></div>}
      <div className="chat-messages" aria-live="polite">{messages.length === 0 && <div className="empty-state"><strong>Try a placement question</strong><p>For example: “What is the average package for CSE in 2026?”, “What does the approved placement policy say?”, or “Show my unread notifications.”</p></div>}
        {messages.map((message, index) => <article className={`chat-message message-${message.role}`} key={`${index}-${message.role}`}><strong>{message.role === "user" ? "You" : "CampusAI"}</strong>{message.role === "assistant" ? (() => { const answer = structureAnswer(message.content); return <div className="assistant-answer">{answer.heading && <h2 className="assistant-answer-heading">{answer.heading}</h2>}<div className="assistant-answer-body">{answer.blocks.map((block, blockIndex) => block.type === "list" ? <ul key={blockIndex}>{block.items.map((item, itemIndex) => <li key={itemIndex}>{item}</li>)}</ul> : <p key={blockIndex}>{block.text}</p>)}</div></div>; })() : <p>{message.content}</p>}</article>)}
        {busy && <div className="loading-panel">Routing your placement question and preparing an answer…</div>}
      </div>
      {error && <div className="notice notice-error">{error}</div>}
      <form className="chat-composer" onSubmit={send}><textarea required minLength={3} maxLength={3000} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about placements, approved files, company details, or notifications…" /><button className="button button-primary" disabled={busy || question.trim().length < 3}>{busy ? "Working…" : "Send"}</button></form>
    </section>
  </div>;
}

export default function ChatPage() { return <RequireAuth><ChatContent /></RequireAuth>; }
