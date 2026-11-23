"use client";

import { useCallback, useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../lib/api";

type StudentProfile = { student_id: string | null; department: string | null; branch: string | null; graduation_year: number | null; cgpa: number | null; semester: number | null; active_backlogs: number | null; historical_backlogs: number | null; technical_skills: string[]; soft_skills: string[]; certifications: string[]; projects: string[]; placement_status: string };

function StudentDetailsContent() {
  const { api, user } = useAuth();
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => setProfile(await api<StudentProfile>("/api/v1/students/me")), [api]);
  useEffect(() => { load().catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load student details.")); }, [load]);
  const show = (value: unknown) => value == null || value === "" ? "Not provided" : String(value);
  const list = (items: string[] | undefined) => items?.length ? items.join(", ") : "Not provided";
  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">STUDENT PROFILE</p><h1>Student details</h1><p className="muted">Your saved account and academic information. Contact the placement office to correct a detail.</p></div><a className="button button-quiet" href="/dashboard">← Back to dashboard</a></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    {!profile ? <div className="panel" role="status">Loading student details…</div> : <>
      <section className="panel"><p className="eyebrow">ACCOUNT</p><h2>{user?.full_name}</h2><dl className="student-profile-grid"><div><dt>Username / email</dt><dd>{user?.email}</dd></div><div><dt>Student ID</dt><dd>{show(profile.student_id)}</dd></div><div><dt>Placement status</dt><dd>{show(profile.placement_status)}</dd></div></dl></section>
      <section className="panel"><p className="eyebrow">ACADEMICS</p><h2>Academic details</h2><dl className="student-profile-grid">{[["Department", profile.department], ["Branch", profile.branch], ["Graduation year", profile.graduation_year], ["CGPA", profile.cgpa], ["Semester", profile.semester], ["Active backlogs", profile.active_backlogs], ["Historical backlogs", profile.historical_backlogs]].map(([label, value]) => <div key={String(label)}><dt>{label}</dt><dd>{show(value)}</dd></div>)}</dl></section>
      <section className="two-column"><div className="panel"><p className="eyebrow">SKILLS</p><h2>Technical skills</h2><p>{list(profile.technical_skills)}</p><h3>Soft skills</h3><p>{list(profile.soft_skills)}</p></div><div className="panel"><p className="eyebrow">EXPERIENCE</p><h2>Certifications</h2><p>{list(profile.certifications)}</p><h3>Projects</h3><p>{list(profile.projects)}</p></div></section>
    </>}
  </div>;
}

export default function StudentDetailsPage() { return <RequireAuth roles={["student"]}><StudentDetailsContent /></RequireAuth>; }
