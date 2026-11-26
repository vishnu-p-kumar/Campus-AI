"use client";

import { ChangeEvent, useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../lib/api";

type Company = { id: number; name: string; industry: string | null; description: string | null; job_roles: string[] };
type Drive = { id: number; company_id: number; company_name: string; title: string; role: string; package_lpa: number | null; location: string | null; application_deadline: string | null; drive_date: string | null; status: string };
type Eligibility = { decision: string; reasons: string[]; missing_fields: string[]; source_document_id: number | null; rule_version: number | null };

function CompaniesContent() {
  const { api } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [drives, setDrives] = useState<Drive[]>([]);
  const [checks, setChecks] = useState<Record<number, Eligibility>>({});
  const [appliedDriveIds, setAppliedDriveIds] = useState<number[]>([]);
  const [resumeFiles, setResumeFiles] = useState<Record<number, File>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [applyingDriveId, setApplyingDriveId] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([
      api<Company[]>("/api/v1/companies/"),
      api<Drive[]>("/api/v1/placement-drives/"),
      api<Array<{ drive_id: number }>>("/api/v1/students/me/applications"),
    ])
      .then(([companyRows, driveRows, applicationRows]) => {
        setCompanies(companyRows); setDrives(driveRows);
        setAppliedDriveIds(applicationRows.map((application) => application.drive_id));
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load placement data"));
  }, [api]);

  async function check(companyId: number) {
    setError("");
    try { setChecks({ ...checks, [companyId]: await api<Eligibility>(`/api/v1/companies/${companyId}/eligibility`) }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Eligibility check failed"); }
  }

  function selectResume(driveId: number, event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) setResumeFiles((current) => ({ ...current, [driveId]: file }));
  }

  async function apply(drive: Drive) {
    const resume = resumeFiles[drive.id];
    if (!resume) { setError("Choose a resume for this role before applying."); return; }
    setError(""); setNotice(""); setApplyingDriveId(drive.id);
    try {
      const form = new FormData();
      form.append("resume", resume);
      await api(`/api/v1/placement-drives/${drive.id}/apply`, { method: "POST", body: form });
      setAppliedDriveIds((current) => current.includes(drive.id) ? current : [...current, drive.id]);
      setNotice(`Applied to ${drive.company_name} · ${drive.role} with ${resume.name}.`);
      setResumeFiles((current) => { const next = { ...current }; delete next[drive.id]; return next; });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Application failed"); }
    finally { setApplyingDriveId(null); }
  }

  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">PLACEMENT OPPORTUNITIES</p><h1>Companies & drives</h1><p className="muted">Published placement rules determine eligibility. Your resume is attached to each application and is not analyzed to calculate eligibility.</p></div></div>
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
    <section className="panel"><div className="section-heading"><div><p className="eyebrow">OPEN ROLES</p><h2>Placement drives</h2><p className="muted">Attach a PDF, DOCX, or TXT resume separately for each role. Eligibility comes from your saved academic profile and the published company criteria.</p></div></div>
      <div className="table-wrap"><table><thead><tr><th>Company</th><th>Role</th><th>Compensation</th><th>Deadline</th><th>Eligibility</th><th>Resume for this role</th><th /></tr></thead><tbody>
        {drives.map((drive) => {
          const hasApplied = appliedDriveIds.includes(drive.id);
          return <tr key={drive.id}><td><strong>{drive.company_name}</strong><small>{drive.title}</small></td><td>{drive.role}</td><td>{drive.package_lpa ? `${drive.package_lpa} LPA` : "Not listed"}</td><td>{drive.application_deadline ? new Date(drive.application_deadline).toLocaleDateString() : "Not listed"}</td><td>{checks[drive.company_id]?.decision.replaceAll("_", " ") || <button className="text-button" onClick={() => check(drive.company_id)}>Check</button>}</td><td>{hasApplied ? <span className="status-pill status-good">Resume submitted</span> : <label className="file-field">{resumeFiles[drive.id]?.name || "Choose resume"}<input aria-label={`Resume for ${drive.company_name} ${drive.role}`} type="file" accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" onChange={(event) => selectResume(drive.id, event)} /></label>}</td><td>{hasApplied ? <span className="status-pill status-good">Applied</span> : <button className="button button-primary button-small" onClick={() => apply(drive)} disabled={drive.status !== "open" || !resumeFiles[drive.id] || applyingDriveId === drive.id}>{applyingDriveId === drive.id ? "Applying…" : "Apply"}</button>}</td></tr>;
        })}
        {!drives.length && <tr><td colSpan={7} className="muted">No eligible placement drives are currently available for your profile.</td></tr>}
      </tbody></table></div>
    </section>
  </div>;
}

export default function CompaniesPage() { return <RequireAuth roles={["student"]}><CompaniesContent /></RequireAuth>; }
