"use client";

import { useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../lib/api";

type Company = { id: number; name: string; industry: string | null; description: string | null; job_roles: string[] };
type Drive = { id: number; company_id: number; company_name: string; title: string; role: string; package_lpa: number | null; location: string | null; application_deadline: string | null; drive_date: string | null; status: string };
type Eligibility = { decision: string; reasons: string[]; missing_fields: string[]; source_document_id: number | null; rule_version: number | null };

function CompaniesContent() {
  const { api } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [drives, setDrives] = useState<Drive[]>([]);
  const [checks, setChecks] = useState<Record<number, Eligibility>>({});
  const [resumeState, setResumeState] = useState<"checking" | "ready" | "missing" | "error">("checking");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    Promise.all([api<Company[]>("/api/v1/companies/"), api<Drive[]>("/api/v1/placement-drives/")])
      .then(([companyRows, driveRows]) => { setCompanies(companyRows); setDrives(driveRows); })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load placement data"));
    api<{ id?: number; analysis?: { id: number } | null }>("/api/v1/resumes/latest")
      .then((result) => setResumeState(result.id || result.analysis?.id ? "ready" : "missing"))
      .catch(() => setResumeState("error"));
  }, [api]);

  async function check(companyId: number) {
    setError("");
    try { setChecks({ ...checks, [companyId]: await api<Eligibility>(`/api/v1/companies/${companyId}/eligibility`) }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Eligibility check failed"); }
  }
  async function apply(driveId: number) {
    setError(""); setNotice("");
    try { await api(`/api/v1/placement-drives/${driveId}/apply`, { method: "POST" }); setNotice("Application recorded. You can follow it from your dashboard."); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Application failed"); }
  }

  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">PLACEMENT OPPORTUNITIES</p><h1>Companies & drives</h1><p className="muted">Eligibility is evaluated with published rules. Incomplete policy evidence goes to manual review.</p></div></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}{notice && <div className="notice notice-success" role="status">{notice}</div>}
    <section className="company-grid">
      {companies.map((company) => {
        const result = checks[company.id];
        return <article className="panel company-card" key={company.id}>
          <div className="company-mark">{company.name.slice(0, 1).toUpperCase()}</div>
          <p className="eyebrow">{company.industry || "Company"}</p><h2>{company.name}</h2>
          <p className="muted">{company.description || "Company information and published criteria are managed by the Placement Office."}</p>
          <div className="tag-row">{company.job_roles.map((role) => <span className="tag" key={role}>{role}</span>)}</div>
          <button className="button button-secondary" onClick={() => check(company.id)}>Check my eligibility</button>
          {result && <div className="eligibility-result">
            <span className={`status-pill ${result.decision === "eligible" ? "status-good" : result.decision === "not_eligible" ? "status-bad" : "status-review"}`}>{result.decision.replaceAll("_", " ")}</span>
            <ul>{result.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>
            {result.source_document_id && <small>Rule source: approved document #{result.source_document_id} · version {result.rule_version}</small>}
          </div>}
        </article>;
      })}
      {!companies.length && <div className="panel empty-state">No eligible companies are currently available for your student profile.</div>}
    </section>
    {resumeState === "missing" && <div className="notice notice-info">Upload and analyze your resume before applying. <a href="/resumes">Upload resume</a>.</div>}
    {resumeState === "error" && <div className="notice notice-info">Could not check your resume status. Reload this page before applying.</div>}
    <section className="panel"><div className="section-heading"><div><p className="eyebrow">OPEN ROLES</p><h2>Placement drives</h2></div></div>
      <div className="table-wrap"><table><thead><tr><th>Company</th><th>Role</th><th>Compensation</th><th>Deadline</th><th>Eligibility</th><th /></tr></thead><tbody>
        {drives.map((drive) => <tr key={drive.id}><td><strong>{drive.company_name}</strong><small>{drive.title}</small></td><td>{drive.role}</td><td>{drive.package_lpa ? `${drive.package_lpa} LPA` : "Not listed"}</td><td>{drive.application_deadline ? new Date(drive.application_deadline).toLocaleDateString() : "Not listed"}</td><td>{checks[drive.company_id]?.decision.replaceAll("_", " ") || <button className="text-button" onClick={() => check(drive.company_id)}>Check</button>}</td><td><button className="button button-primary button-small" onClick={() => apply(drive.id)} disabled={drive.status !== "open" || resumeState !== "ready"}>Apply</button></td></tr>)}
        {!drives.length && <tr><td colSpan={6} className="muted">No eligible placement drives are currently available for your profile.</td></tr>}
      </tbody></table></div>
    </section>
  </div>;
}

export default function CompaniesPage() { return <RequireAuth roles={["student"]}><CompaniesContent /></RequireAuth>; }
