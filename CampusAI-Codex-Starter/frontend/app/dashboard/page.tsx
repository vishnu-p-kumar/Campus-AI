"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../lib/api";

type DashboardData = {
  student: { name: string; email: string };
  profile_completion: number;
  eligibility_review_needed: number;
  eligible_drives: { drive_id: number; company: string; role: string; deadline: string | null }[];
  upcoming_drives: { id: number; company: string; title: string; role: string; deadline: string | null; date: string | null }[];
  applications: { id: number; company: string; role: string; status: string; applied_at: string }[];
  profile: Record<string, unknown> | null;
};

function DashboardContent() {
  const { api, user, logout } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    const result = await api<DashboardData>("/api/v1/students/me/dashboard");
    setData(result);
  }, [api]);
  useEffect(() => { load().catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load dashboard")); }, [load]);
  async function deleteAccount() {
    if (!window.confirm("Permanently delete your CampusAI account, profile, chat history, resume summaries, and practice history? This cannot be undone.")) return;
    try { await api("/api/v1/students/me", { method: "DELETE" }); await logout(); window.location.assign("/"); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Account could not be deleted"); }
  }
  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">STUDENT WORKSPACE</p><h1>Hello, {user?.full_name.split(" ")[0]}</h1><p className="muted">Your placement activity and next steps, based on your saved profile.</p></div><Link className="button button-primary" href="/companies">Explore companies</Link></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    {!data ? <div className="panel loading-panel">Loading dashboard data…</div> : <>
      <section className="metric-grid">
        <article className="metric-card"><span>Profile completion</span><strong>{data.profile_completion}%</strong><div className="progress"><i style={{ width: `${data.profile_completion}%` }} /></div></article>
        <article className="metric-card"><span>Eligible open drives</span><strong>{data.eligible_drives.length}</strong><small>Based on published, approved criteria</small></article>
        <article className="metric-card"><span>Manual reviews</span><strong>{data.eligibility_review_needed}</strong><small>Some policy or profile details are incomplete</small></article>
        <article className="metric-card"><span>Applications</span><strong>{data.applications.length}</strong><small>Current application records</small></article>
      </section>
      <section className="two-column">
        <div className="panel"><div className="section-heading"><div><p className="eyebrow">PROFILE</p><h2>Academic details</h2></div><Link href="/student-details">View all details</Link></div>
          {data.profile ? <dl className="student-profile-grid">{[["Department", data.profile.department], ["Branch", data.profile.branch], ["Graduation year", data.profile.graduation_year], ["CGPA", data.profile.cgpa], ["Semester", data.profile.semester], ["Active backlogs", data.profile.active_backlogs]].map(([label, value]) => <div key={String(label)}><dt>{String(label)}</dt><dd>{value == null || value === "" ? "Not provided" : String(value)}</dd></div>)}</dl> : <p className="empty-state">Your academic details will appear here after the placement office adds them.</p>}
        </div>
        <div className="panel"><div className="section-heading"><div><p className="eyebrow">MATCHES</p><h2>Eligible drives</h2></div><Link href="/companies">View all</Link></div>
          {data.eligible_drives.length ? <ul className="list-clean">{data.eligible_drives.map((item) => <li key={item.drive_id}><div><strong>{item.company}</strong><span>{item.role}</span></div><span className="status-pill status-good">Eligible</span></li>)}</ul> : <div className="empty-state"><strong>No confirmed matches yet</strong><p>Complete your profile and review open drives. Incomplete criteria are marked for manual review.</p></div>}
          {data.eligibility_review_needed > 0 && <p className="muted small-note">{data.eligibility_review_needed} listed drive(s) need officer review because a profile value or approved rule source is missing.</p>}
        </div>
      </section>
      <section className="two-column">
        <div className="panel"><div className="section-heading"><div><p className="eyebrow">UPCOMING</p><h2>Placement drives</h2></div><Link href="/companies">Browse</Link></div>
          {data.upcoming_drives.length ? <ul className="list-clean">{data.upcoming_drives.slice(0, 5).map((drive) => <li key={drive.id}><div><strong>{drive.company} · {drive.role}</strong><span>{drive.title}</span></div><span className="muted">{drive.date ? new Date(drive.date).toLocaleDateString() : "Date pending"}</span></li>)}</ul> : <p className="empty-state">No open placement drives have been published yet.</p>}
        </div>
        <div className="panel"><div className="section-heading"><div><p className="eyebrow">ACTIVITY</p><h2>Applications</h2></div></div>
          {data.applications.length ? <ul className="list-clean">{data.applications.map((item) => <li key={item.id}><div><strong>{item.company} · {item.role}</strong><span>{new Date(item.applied_at).toLocaleDateString()}</span></div><span className="status-pill">{item.status}</span></li>)}</ul> : <p className="empty-state">Your submitted applications will appear here.</p>}
        </div>
      </section>
      <section className="panel"><p className="eyebrow">DATA CONTROL</p><h2>Delete student account</h2><p className="muted">This permanently removes your profile, chats, resume summaries, skill gap history, notifications and practice sessions.</p><button className="button button-secondary" onClick={deleteAccount}>Delete my account and data</button></section>
    </>}
  </div>;
}

export default function DashboardPage() { return <RequireAuth roles={["student"]}><DashboardContent /></RequireAuth>; }
