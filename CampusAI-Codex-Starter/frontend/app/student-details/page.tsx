"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { RequireAuth, useAuth } from "../lib/api";

type StudentProfile = {
  student_id: string | null;
  department: string | null;
  branch: string | null;
  graduation_year: number | null;
  cgpa: number | null;
  semester: number | null;
  active_backlogs: number | null;
  historical_backlogs: number | null;
  technical_skills: string[];
  soft_skills: string[];
  certifications: string[];
  projects: string[];
  placement_status: string;
};

type PortfolioDraft = {
  technical_skills: string;
  soft_skills: string;
  certifications: string;
  projects: string;
};

const emptyDraft: PortfolioDraft = { technical_skills: "", soft_skills: "", certifications: "", projects: "" };
const asDraft = (profile: StudentProfile): PortfolioDraft => ({
  technical_skills: profile.technical_skills.join(", "),
  soft_skills: profile.soft_skills.join(", "),
  certifications: profile.certifications.join(", "),
  projects: profile.projects.join(", "),
});

function StudentDetailsContent() {
  const { api, user } = useAuth();
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [draft, setDraft] = useState<PortfolioDraft>(emptyDraft);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    const value = await api<StudentProfile>("/api/v1/students/me");
    setProfile(value);
    setDraft(asDraft(value));
  }, [api]);

  useEffect(() => {
    load().catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load student details."));
  }, [load]);

  const savePortfolio = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSaved(false);
    const portfolio = Object.fromEntries(Object.entries(draft).map(([key, value]) => [
      key, value.split(",").map((item) => item.trim()).filter(Boolean),
    ]));
    try {
      const updated = await api<StudentProfile>("/api/v1/students/me/portfolio", {
        method: "PATCH",
        body: JSON.stringify(portfolio),
      });
      setProfile(updated);
      setDraft(asDraft(updated));
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save your student details.");
    } finally {
      setSaving(false);
    }
  };

  const show = (value: unknown) => value == null || value === "" ? "Not provided" : String(value);

  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">STUDENT PROFILE</p><h1>Student details</h1><p className="muted">Update your skills, certifications, and projects here. Contact the placement office to correct account or academic details.</p></div><Link className="button button-quiet" href="/dashboard">← Back to dashboard</Link></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    {!profile ? <div className="panel" role="status">Loading student details…</div> : <>
      <section className="panel"><p className="eyebrow">ACCOUNT</p><h2>{user?.full_name}</h2><dl className="student-profile-grid"><div><dt>Username / email</dt><dd>{user?.email}</dd></div><div><dt>Student ID</dt><dd>{show(profile.student_id)}</dd></div><div><dt>Placement status</dt><dd>{show(profile.placement_status)}</dd></div></dl></section>
      <section className="panel"><p className="eyebrow">ACADEMICS</p><h2>Academic details</h2><dl className="student-profile-grid">{[["Department", profile.department], ["Branch", profile.branch], ["Graduation year", profile.graduation_year], ["CGPA", profile.cgpa], ["Semester", profile.semester], ["Active backlogs", profile.active_backlogs], ["Historical backlogs", profile.historical_backlogs]].map(([label, value]) => <div key={String(label)}><dt>{label}</dt><dd>{show(value)}</dd></div>)}</dl></section>
      <form className="panel form-stack" onSubmit={savePortfolio}>
        <p className="eyebrow">SKILLS & EXPERIENCE</p><h2>Skills, certifications, and projects</h2>
        <p className="muted">Enter items separated by commas. These details are saved to your student profile.</p>
        <label>Technical skills<textarea rows={3} maxLength={8000} value={draft.technical_skills} onChange={(event) => setDraft({ ...draft, technical_skills: event.target.value })} placeholder="Python, SQL, React" /></label>
        <label>Soft skills<textarea rows={3} maxLength={8000} value={draft.soft_skills} onChange={(event) => setDraft({ ...draft, soft_skills: event.target.value })} placeholder="Communication, teamwork" /></label>
        <label>Certifications<textarea rows={3} maxLength={8000} value={draft.certifications} onChange={(event) => setDraft({ ...draft, certifications: event.target.value })} placeholder="Cloud Fundamentals" /></label>
        <label>Projects<textarea rows={3} maxLength={8000} value={draft.projects} onChange={(event) => setDraft({ ...draft, projects: event.target.value })} placeholder="Placement portal" /></label>
        <div className="section-heading"><button className="button button-primary" type="submit" disabled={saving}>{saving ? "Saving…" : "Save student details"}</button>{saved && <span className="muted" role="status">Student details saved.</span>}</div>
      </form>
    </>}
  </div>;
}

export default function StudentDetailsPage() { return <RequireAuth roles={["student"]}><StudentDetailsContent /></RequireAuth>; }
