"use client";

import { useCallback, useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../../lib/api";

type UserRow = { id: number; full_name: string; email: string; role: string; is_active: boolean; created_at: string };

function AccessControlContent() {
  const { api } = useAuth();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

  const loadUsers = useCallback(async () => {
    const rows = await api<UserRow[]>("/api/v1/admin/users");
    setUsers(rows);
  }, [api]);

  useEffect(() => {
    loadUsers().catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load user access."))
      .finally(() => setLoading(false));
  }, [loadUsers]);

  async function updateUser(id: number, update: { role?: string; is_active?: boolean }) {
    setError("");
    setNotice("");
    try {
      await api(`/api/v1/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(update) });
      await loadUsers();
      setNotice("User access updated and recorded in the audit log.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "User access could not be updated.");
      await loadUsers().catch(() => undefined);
    }
  }

  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">ADMINISTRATION</p><h1>Access control</h1><p className="muted">Review registered accounts and manage user roles and access.</p></div><a className="button button-quiet back-to-tools" href="/admin" aria-label="Back to admin dashboard">{"\u2190"} Back to admin</a></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}{notice && <div className="notice notice-success" role="status">{notice}</div>}
    <section className="panel"><h2>User management ({users.length})</h2>
      {loading ? <p className="muted" role="status">Loading user accounts…</p> : <div className="table-wrap"><table><thead><tr><th>User</th><th>Role</th><th>Access</th><th>Registered</th></tr></thead><tbody>
        {users.map((row) => <tr key={row.id}><td>{row.full_name}<small>{row.email}</small></td><td><select value={row.role} aria-label={`Role for ${row.email}`} onChange={(event) => updateUser(row.id, { role: event.target.value })}><option value="student">Student</option><option value="placement_officer">Placement Officer</option><option value="administrator">Administrator</option></select></td><td><button type="button" className="text-button" onClick={() => updateUser(row.id, { is_active: !row.is_active })}>{row.is_active ? "Disable" : "Enable"}</button><span className="status-pill">{row.is_active ? "Active" : "Disabled"}</span></td><td>{new Date(row.created_at).toLocaleDateString()}</td></tr>)}
        {!users.length && <tr><td colSpan={4} className="muted">No user accounts.</td></tr>}
      </tbody></table></div>}
    </section>
  </div>;
}

export default function AdminAccessControlPage() {
  return <RequireAuth roles={["administrator"]}><AccessControlContent /></RequireAuth>;
}
