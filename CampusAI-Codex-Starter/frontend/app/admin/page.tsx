"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { RequireAuth, useAuth } from "../lib/api";

type Analytics = { students: number; companies: number; open_drives: number; documents_pending_review: number; documents_approved: number; interview_sessions: number; placements: number; chat_messages: number };
type DocumentRow = { id: number; title: string; category: string; filename: string; version: number; approval_status: string; ingestion_status: string; ingestion_error: string | null; effective_date: string | null; expiry_date: string | null; suggested_category: string | null; classification_score: number | null; metadata_candidates: { date_candidates?: { effective?: string[]; expiry?: string[] } } };
type CompanyRow = { id: number; name: string; industry: string | null };
type DriveRow = { id: number; title: string; company_name: string; role: string; status: string };
type ApplicationRow = { id: number; student_user_id: number; student_name: string; company_id: number; company: string; role: string; status: string; applied_at: string; resume_filename: string | null };
type PlacementRow = { id: number; student: string; company: string; role: string; package_lpa: number | null; placed_at: string };
function AdminContent() {
  const { api, download, user } = useAuth();
  const [metrics, setMetrics] = useState<Analytics | null>(null);
  const [students, setStudents] = useState<{ id: number; full_name: string; email: string }[]>([]);
  const [companies, setCompanies] = useState<CompanyRow[]>([]);
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [queuedUploadPending, setQueuedUploadPending] = useState(false);
  const documentFetchSequence = useRef(0);
  const [drives, setDrives] = useState<DriveRow[]>([]);
  const [applications, setApplications] = useState<ApplicationRow[]>([]);
  const [placements, setPlacements] = useState<PlacementRow[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [drive, setDrive] = useState({ companyId: "", title: "", role: "", packageLpa: "", location: "", deadline: "", driveDate: "" });
  const [notification, setNotification] = useState({ userId: "", title: "", message: "" });
  const [company, setCompany] = useState({ name: "", industry: "", role: "", minimumCgpa: "", branches: "", maxBacklogs: "", source: "" });
  const refreshDocuments = useCallback(async () => {
    const sequence = ++documentFetchSequence.current;
    const rows = await api<DocumentRow[]>("/api/v1/documents/");
    if (sequence === documentFetchSequence.current) setDocuments(rows);
    return rows;
  }, [api]);
  const load = useCallback(async () => {
    const [a, s, c, dr, ar, pr] = await Promise.all([
      api<Analytics>("/api/v1/admin/analytics"), api<typeof students>("/api/v1/students/"),
      api<CompanyRow[]>("/api/v1/companies/"),
      api<DriveRow[]>("/api/v1/placement-drives/"),
      api<ApplicationRow[]>("/api/v1/admin/applications"), api<PlacementRow[]>("/api/v1/admin/placement-records"),
    ]);
    setMetrics(a); setStudents(s); setCompanies(c); setDrives(dr); setApplications(ar); setPlacements(pr);
    await refreshDocuments();
  }, [api, refreshDocuments]);
  useEffect(() => { load().catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load admin data")); }, [load]);
  useEffect(() => {
    const hasPending = documents.some((doc) => doc.ingestion_status === "queued" || doc.ingestion_status === "processing");
    if (!queuedUploadPending && !hasPending) return;
    const timer = window.setInterval(() => {
      refreshDocuments().then((rows) => {
        if (!rows.some((doc) => doc.ingestion_status === "queued" || doc.ingestion_status === "processing")) setQueuedUploadPending(false);
      }).catch((cause) => setError(cause instanceof Error ? cause.message : "Could not refresh document processing status"));
    }, 4000);
    return () => window.clearInterval(timer);
  }, [documents, queuedUploadPending, refreshDocuments]);
  async function upload(event: FormEvent) {
    event.preventDefault(); if (!uploadFile) return;
    setError(""); setNotice("");
    try {
      const form = new FormData(); form.append("file", uploadFile); form.append("title", uploadFile.name.replace(/\.[^.]+$/, "")); form.append("category", "placement-policy");
      const result = await api<{ id: number; chunks_created: number; ingestion_status: string }>("/api/v1/documents/upload", { method: "POST", body: form });
      if (result.ingestion_status === "queued") setQueuedUploadPending(true);
      setNotice(result.ingestion_status === "queued" ? `Document #${result.id} uploaded and queued for text extraction.` : `Document #${result.id} uploaded with ${result.chunks_created} text chunks. It is pending officer approval.`); setUploadFile(null); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Document upload failed"); }
  }
  async function approve(id: number) {
    setError(""); setNotice("");
    try { await api(`/api/v1/documents/${id}/approve`, { method: "POST" }); setNotice(`Document #${id} approved and made available for policy retrieval.`); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Approval failed"); }
  }
  async function reject(id: number) {
    setError(""); setNotice("");
    try { await api(`/api/v1/documents/${id}/reject`, { method: "POST" }); setNotice(`Document #${id} rejected and kept out of student retrieval.`); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Rejection failed"); }
  }
  async function createCompany(event: FormEvent) {
    event.preventDefault(); setError(""); setNotice("");
    try {
      await api("/api/v1/companies/", { method: "POST", body: JSON.stringify({
        name: company.name, industry: company.industry || null, job_roles: company.role ? [company.role] : [],
        min_cgpa: company.minimumCgpa ? Number(company.minimumCgpa) : null,
        eligible_branches: company.branches ? company.branches.split(",").map((x) => x.trim()).filter(Boolean) : null,
        max_active_backlogs: company.maxBacklogs === "" ? null : Number(company.maxBacklogs),
        criteria_reviewed: Boolean(company.source), source_document_id: company.source ? Number(company.source) : null,
      }) });
      setNotice("Company information saved. Eligibility stays in manual review unless criteria are source-linked and marked reviewed.");
      setCompany({ name: "", industry: "", role: "", minimumCgpa: "", branches: "", maxBacklogs: "", source: "" }); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Company could not be saved"); }
  }
  async function createDrive(event: FormEvent) {
    event.preventDefault(); setError(""); setNotice("");
    try {
      await api("/api/v1/placement-drives/", { method: "POST", body: JSON.stringify({ company_id: Number(drive.companyId), title: drive.title, role: drive.role, package_lpa: drive.packageLpa ? Number(drive.packageLpa) : null, location: drive.location || null, application_deadline: drive.deadline ? new Date(drive.deadline).toISOString() : null, drive_date: drive.driveDate ? new Date(drive.driveDate).toISOString() : null }) });
      setDrive({ companyId: "", title: "", role: "", packageLpa: "", location: "", deadline: "", driveDate: "" }); setNotice("Placement drive published."); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Drive could not be created"); }
  }
  async function closeDrive(id: number) {
    try { await api(`/api/v1/placement-drives/${id}/close`, { method: "PATCH" }); setNotice(`Drive #${id} closed.`); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Drive could not be closed"); }
  }
  async function updateApplication(id: number, status: string) {
    try { await api(`/api/v1/placement-drives/applications/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }); setNotice(`Application #${id} updated.`); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Application status could not be changed"); }
  }
  async function downloadApplicationResume(row: ApplicationRow) {
    try {
      const blob = await download(`/api/v1/placement-drives/applications/${row.id}/resume`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = row.resume_filename || `application-${row.id}-resume`;
      document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Resume could not be downloaded"); }
  }
  async function sendNotification(event: FormEvent) {
    event.preventDefault(); setError(""); setNotice("");
    try { await api("/api/v1/notifications/", { method: "POST", body: JSON.stringify({ user_id: Number(notification.userId), title: notification.title, message: notification.message }) }); setNotification({ userId: "", title: "", message: "" }); setNotice("Notification sent to the selected account."); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Notification could not be sent"); }
  }
  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">PLACEMENT OFFICE</p><h1>Administration</h1><p className="muted">Manage verified placement information, student records and documents.</p></div>{user?.role === "administrator" && <div className="admin-header-actions"><a className="button button-secondary" href="/admin/students">Student records</a><a className="button button-secondary" href="/admin/audit">Audit</a><a className="button button-secondary" href="/admin/access-control">Access control</a></div>}</div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}{notice && <div className="notice notice-success" role="status">{notice}</div>}
    {metrics && <><section className="metric-grid">{[["Students", metrics.students], ["Companies", metrics.companies], ["Open drives", metrics.open_drives], ["Placements", metrics.placements], ["Pending documents", metrics.documents_pending_review], ["Chat messages", metrics.chat_messages]].map(([label, value]) => <article className="metric-card" key={label}><span>{label}</span><strong>{value}</strong></article>)}</section><section className="panel"><p className="eyebrow">LIVE COUNTS</p><h2>Placement workspace overview</h2><p className="muted">Counts from the current CampusAI database.</p><div style={{ height: 240, width: "100%" }}><ResponsiveContainer><BarChart data={[{ name: "Students", count: metrics.students }, { name: "Companies", count: metrics.companies }, { name: "Open drives", count: metrics.open_drives }, { name: "Placements", count: metrics.placements }, { name: "Pending docs", count: metrics.documents_pending_review }, { name: "Approved docs", count: metrics.documents_approved }]} margin={{ top: 10, right: 12, left: 0, bottom: 8 }}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="count" fill="#176b4c" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer></div></section></>}
    <section className="two-column">
      <div className="panel"><p className="eyebrow">KNOWLEDGE BASE</p><h2>Upload placement document</h2><p className="muted">PDF, DOCX, or UTF-8 TXT. Scanned PDFs need OCR before their contents can be indexed.</p><form className="form-stack" onSubmit={upload}><label>Document<input type="file" accept=".pdf,.docx,.txt" required onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)} /></label><button className="button button-primary" disabled={!uploadFile}>Upload for review</button></form>
        <div className="table-wrap"><table><thead><tr><th>Document</th><th>Version</th><th>Status</th><th /></tr></thead><tbody>{documents.map((doc) => <tr key={doc.id}><td>{doc.title}<small>{doc.category} · {doc.filename}{doc.ingestion_error && ` · ${doc.ingestion_error}`}</small>{doc.suggested_category && <small>Text classification suggestion: {doc.suggested_category} (match score {doc.classification_score}; review manually)</small>}{Boolean(doc.metadata_candidates?.date_candidates?.effective?.length) && <small>Effective date candidates: {doc.metadata_candidates.date_candidates?.effective?.join(", ")}</small>}{Boolean(doc.metadata_candidates?.date_candidates?.expiry?.length) && <small>Expiry date candidates: {doc.metadata_candidates.date_candidates?.expiry?.join(", ")}</small>}</td><td>v{doc.version}</td><td><span className="status-pill">{doc.approval_status} · {doc.ingestion_status}</span></td><td>{doc.approval_status === "pending" && <>{doc.ingestion_status === "completed" && <button className="text-button" onClick={() => approve(doc.id)}>Approve</button>}<button className="text-button" onClick={() => reject(doc.id)}>Reject</button></>}</td></tr>)}{!documents.length && <tr><td colSpan={4} className="muted">No documents uploaded yet.</td></tr>}</tbody></table></div>

      </div>
      <div className="panel"><p className="eyebrow">DIRECTORY</p><h2>Add and publish</h2>
        <h3>Add verified company</h3><form className="form-grid" onSubmit={createCompany}><label>Name<input required value={company.name} onChange={(e) => setCompany({ ...company, name: e.target.value })} /></label><label>Industry<input value={company.industry} onChange={(e) => setCompany({ ...company, industry: e.target.value })} /></label><label>Role<input value={company.role} onChange={(e) => setCompany({ ...company, role: e.target.value })} /></label><label>Minimum CGPA<input type="number" min="0" max="10" step="0.1" value={company.minimumCgpa} onChange={(e) => setCompany({ ...company, minimumCgpa: e.target.value })} /></label><label>Eligible branches (comma separated)<input value={company.branches} onChange={(e) => setCompany({ ...company, branches: e.target.value })} /></label><label>Maximum active backlogs<input type="number" min="0" value={company.maxBacklogs} onChange={(e) => setCompany({ ...company, maxBacklogs: e.target.value })} /></label><label>Approved source document<select value={company.source} onChange={(e) => setCompany({ ...company, source: e.target.value })}><option value="">Not linked</option>{documents.filter((doc) => doc.approval_status === "approved").map((doc) => <option key={doc.id} value={doc.id}>{doc.title} v{doc.version} · #{doc.id}</option>)}</select></label><div className="form-actions"><button className="button button-secondary">Save company</button></div></form>
        <h3>Publish placement drive</h3><form className="form-grid" onSubmit={createDrive}><label>Company<select required value={drive.companyId} onChange={(e) => setDrive({ ...drive, companyId: e.target.value })}><option value="">Select a company</option>{companies.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label><label>Drive title<input required value={drive.title} onChange={(e) => setDrive({ ...drive, title: e.target.value })} /></label><label>Role<input required value={drive.role} onChange={(e) => setDrive({ ...drive, role: e.target.value })} /></label><label>Package (LPA)<input type="number" min="0" step="0.1" value={drive.packageLpa} onChange={(e) => setDrive({ ...drive, packageLpa: e.target.value })} /></label><label>Location<input value={drive.location} onChange={(e) => setDrive({ ...drive, location: e.target.value })} /></label><label>Application deadline<input type="datetime-local" value={drive.deadline} onChange={(e) => setDrive({ ...drive, deadline: e.target.value })} /></label><label>Drive date<input type="datetime-local" value={drive.driveDate} onChange={(e) => setDrive({ ...drive, driveDate: e.target.value })} /></label><div className="form-actions"><button className="button button-secondary">Publish drive</button></div></form>
        <div className="table-wrap"><table><thead><tr><th>Drive</th><th>Role</th><th>Status</th><th /></tr></thead><tbody>{drives.map((row) => <tr key={row.id}><td>{row.company_name}<small>{row.title}</small></td><td>{row.role}</td><td>{row.status}</td><td>{row.status === "open" && <button className="text-button" onClick={() => closeDrive(row.id)}>Close</button>}</td></tr>)}</tbody></table></div>
      </div>
    </section>
    <section className="panel"><p className="eyebrow">COMPANY RECORDS</p><h2>Registered companies ({companies.length})</h2><p className="muted">Choose a company to view students who applied to its placement drives.</p><ul className="list-clean">{companies.map((row) => {
      const applicantCount = new Set(applications.filter((application) => application.company_id === row.id).map((application) => application.student_user_id)).size;
      return <li key={row.id}><div><strong>{row.name}</strong><span>{row.industry || "Industry not provided"} · {applicantCount} registered student{applicantCount === 1 ? "" : "s"}</span></div><a className="text-button" href={`/admin/companies/${row.id}/students`}>View students</a></li>;
    })}{!companies.length && <li className="muted">No companies registered yet.</li>}</ul></section>
    <section className="two-column"><div className="panel"><p className="eyebrow">APPLICATION PIPELINE</p><h2>Applications</h2><div className="table-wrap"><table><thead><tr><th>Student</th><th>Company / role</th><th>Resume</th><th>Status</th><th>Applied</th></tr></thead><tbody>{applications.map((row) => <tr key={row.id}><td>{row.student_name}<small>{row.student_user_id}</small></td><td>{row.company}<small>{row.role}</small></td><td>{row.resume_filename ? <button className="text-button" onClick={() => downloadApplicationResume(row)}>{row.resume_filename}</button> : "No resume attached"}</td><td><select aria-label={`Application status for ${row.student_name}`} value={row.status} onChange={(e) => updateApplication(row.id, e.target.value)}><option value="applied">Applied</option><option value="screening">Screening</option><option value="interview">Interview</option><option value="selected">Selected</option><option value="rejected">Rejected</option><option value="withdrawn">Withdrawn</option></select></td><td>{new Date(row.applied_at).toLocaleDateString()}</td></tr>)}{!applications.length && <tr><td colSpan={5}>No applications have been submitted.</td></tr>}</tbody></table></div></div><div className="panel"><p className="eyebrow">OUTCOMES</p><h2>Placement records ({placements.length})</h2><ul className="list-clean">{placements.map((row) => <li key={row.id}><div><strong>{row.student} · {row.company}</strong><span>{row.role}{row.package_lpa ? ` · ${row.package_lpa} LPA` : ""}</span></div></li>)}{!placements.length && <li className="muted">Selected applicants create placement records.</li>}</ul></div></section>
<section className="panel"><p className="eyebrow">COMMUNICATIONS</p><h2>Send a student notification</h2><form className="form-grid" onSubmit={sendNotification}><label>Student account<select required value={notification.userId} onChange={(e) => setNotification({ ...notification, userId: e.target.value })}><option value="">Select student</option>{students.map((student) => <option key={student.id} value={student.id}>{student.full_name} · {student.email}</option>)}</select></label><label>Title<input required maxLength={180} value={notification.title} onChange={(e) => setNotification({ ...notification, title: e.target.value })} /></label><label>Message<textarea required maxLength={2000} value={notification.message} onChange={(e) => setNotification({ ...notification, message: e.target.value })} /></label><div className="form-actions"><button className="button button-secondary">Send notification</button></div></form></section>
  </div>;
}

export default function AdminPage() { return <RequireAuth roles={["administrator", "placement_officer"]}><AdminContent /></RequireAuth>; }
