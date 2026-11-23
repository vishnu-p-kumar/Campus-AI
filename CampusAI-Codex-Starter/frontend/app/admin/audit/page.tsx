"use client";

import { useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../../lib/api";

type AuditEntry = { id: number; actor_user_id: number | null; action: string; resource_type: string; resource_id: string | null; details: Record<string, unknown> | null; created_at: string };

function AuditContent() {
  const { api } = useAuth();
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<AuditEntry[]>("/api/v1/admin/audit-logs?limit=500")
      .then(setEntries)
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load audit activity."))
      .finally(() => setLoading(false));
  }, [api]);

  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">ADMINISTRATION</p><h1>Audit</h1><p className="muted">Recent administrative actions recorded by CampusAI.</p></div><a className="button button-quiet back-to-tools" href="/admin" aria-label="Back to admin dashboard">{"\u2190"} Back to admin</a></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    <section className="panel"><h2>Recent admin activity</h2>
      {loading ? <p className="muted" role="status">Loading audit activity…</p> : entries.length ? <div className="table-wrap"><table><thead><tr><th>Date and time</th><th>Actor</th><th>Action</th><th>Resource</th><th>Details</th></tr></thead><tbody>
        {entries.map((entry) => <tr key={entry.id}><td>{new Date(entry.created_at).toLocaleString()}</td><td>{entry.actor_user_id ? `User #${entry.actor_user_id}` : "System or erased account"}</td><td>{entry.action}</td><td>{entry.resource_type}{entry.resource_id ? ` #${entry.resource_id}` : ""}</td><td>{entry.details && Object.keys(entry.details).length ? JSON.stringify(entry.details) : "—"}</td></tr>)}
      </tbody></table></div> : <p className="empty-state">No admin activity has been recorded yet.</p>}
    </section>
  </div>;
}

export default function AdminAuditPage() {
  return <RequireAuth roles={["administrator"]}><AuditContent /></RequireAuth>;
}
