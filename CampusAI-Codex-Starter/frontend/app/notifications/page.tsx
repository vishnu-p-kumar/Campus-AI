"use client";

import { useCallback, useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../lib/api";

type Notification = { id: number; title: string; message: string; read: boolean; created_at: string };

function NotificationContent() {
  const { api } = useAuth();
  const [rows, setRows] = useState<Notification[]>([]);
  const [error, setError] = useState("");
  const load = useCallback(async () => setRows(await api<Notification[]>("/api/v1/notifications/")), [api]);
  useEffect(() => { load().catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load notifications")); }, [load]);
  async function markRead(id: number) {
    try { await api(`/api/v1/notifications/${id}/read`, { method: "POST" }); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not mark notification read"); }
  }
  return <div className="stack-xl"><div className="page-heading"><div><p className="eyebrow">STUDENT WORKSPACE</p><h1>Notifications</h1><p className="muted">Updates sent by placement staff appear here.</p></div></div>{error && <div className="notice notice-error">{error}</div>}<section className="panel"><ul className="list-clean">{rows.map((row) => <li key={row.id}><div><strong>{row.title} {!row.read && <span className="status-pill status-good">New</span>}</strong><span>{row.message}</span><small>{new Date(row.created_at).toLocaleString()}</small></div>{!row.read && <button className="text-button" onClick={() => markRead(row.id)}>Mark read</button>}</li>)}{!rows.length && <li className="empty-state">No notifications yet.</li>}</ul></section></div>;
}

export default function NotificationsPage() { return <RequireAuth><NotificationContent /></RequireAuth>; }
