"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../../lib/api";

type Student = {
  id: number; full_name: string; email: string;
  profile: { student_id: string | null; department: string | null; branch: string | null; graduation_year: number | null; cgpa: number | null; semester: number | null; active_backlogs: number | null; historical_backlogs: number | null; placement_status: string };
};
type StudentForm = { full_name: string; email: string; password: string; student_id: string; department: string; branch: string; graduation_year: string; cgpa: string; semester: string; active_backlogs: string; historical_backlogs: string; placement_status: string };
const blankForm: StudentForm = { full_name: "", email: "", password: "", student_id: "", department: "", branch: "", graduation_year: "", cgpa: "", semester: "", active_backlogs: "", historical_backlogs: "", placement_status: "seeking" };
const numericFields = ["graduation_year", "cgpa", "semester", "active_backlogs", "historical_backlogs"] as const;

function toForm(student?: Student): StudentForm {
  if (!student) return { ...blankForm };
  const profile = student.profile ?? {};
  return { full_name: student.full_name, email: student.email, password: "", student_id: profile.student_id ?? "", department: profile.department ?? "", branch: profile.branch ?? "", graduation_year: profile.graduation_year?.toString() ?? "", cgpa: profile.cgpa?.toString() ?? "", semester: profile.semester?.toString() ?? "", active_backlogs: profile.active_backlogs?.toString() ?? "", historical_backlogs: profile.historical_backlogs?.toString() ?? "", placement_status: profile.placement_status ?? "seeking" };
}

function studentPayload(form: StudentForm, creating: boolean) {
  const payload: Record<string, unknown> = { ...form, full_name: form.full_name.trim(), email: form.email.trim() };
  for (const key of numericFields) payload[key] = form[key] === "" ? null : Number(form[key]);
  if (!creating && !form.password) delete payload.password;
  return payload;
}

function AdminStudentsContent() {
  const { api } = useAuth();
  const [students, setStudents] = useState<Student[]>([]);
  const [form, setForm] = useState<StudentForm>({ ...blankForm });
  const [editingId, setEditingId] = useState<number | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const load = useCallback(async () => setStudents(await api<Student[]>("/api/v1/admin/students")), [api]);
  useEffect(() => { load().catch((cause) => setError(cause instanceof Error ? cause.message : "Could not load student records.")).finally(() => setLoading(false)); }, [load]);

  function startCreate() { setEditingId(null); setForm({ ...blankForm }); setShowForm(true); setNotice(""); setError(""); }
  function startEdit(student: Student) { setEditingId(student.id); setForm(toForm(student)); setShowForm(true); setNotice(""); setError(""); window.scrollTo({ top: 0, behavior: "smooth" }); }
  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(""); setNotice("");
    try {
      const payload = studentPayload(form, editingId === null);
      if (editingId === null) await api("/api/v1/admin/students", { method: "POST", body: JSON.stringify(payload) });
      else await api(`/api/v1/admin/students/${editingId}`, { method: "PUT", body: JSON.stringify(payload) });
      await load(); setNotice(editingId === null ? "Student account created. Share the username and password securely with the student." : "Student details updated.");
      setForm({ ...blankForm }); setEditingId(null); setShowForm(false);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Student details could not be saved."); }
    finally { setSaving(false); }
  }

  const field = (key: keyof StudentForm, label: string, type = "text", required = false, hint?: string) => <label key={key}>{label}{hint && <small>{hint}</small>}<input required={required} type={type} value={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.value })} /></label>;
  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">ADMINISTRATION</p><h1>Student records</h1><p className="muted">Create student accounts and manage the student details recorded in the placement spreadsheet.</p></div><div className="admin-header-actions"><a className="button button-quiet" href="/admin">← Back to admin</a><button className="button button-primary" type="button" onClick={startCreate}>Add student</button></div></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}{notice && <div className="notice notice-success" role="status">{notice}</div>}
    {showForm && <section className="panel"><div className="section-heading"><div><p className="eyebrow">STUDENT ACCOUNT</p><h2>{editingId === null ? "Add student" : "Edit student details"}</h2></div><button type="button" className="button button-quiet" onClick={() => setShowForm(false)}>Close</button></div>
      <p className="muted">Username is the student’s email address. {editingId === null ? "Create a temporary password for the student to use at sign in." : "Leave password blank to keep the current password."}</p>
      <form className="form-grid" onSubmit={save}>
        {field("full_name", "Full name", "text", true)}{field("email", "Username / college email", "email", true)}{field("password", editingId === null ? "Initial password" : "New password", "password", editingId === null, "At least 6 characters")}
        {field("student_id", "Student ID")}{field("department", "Department")}{field("branch", "Branch")}{field("graduation_year", "Graduation year", "number")}{field("cgpa", "CGPA", "number")}{field("semester", "Semester", "number")}{field("active_backlogs", "Active backlogs", "number")}{field("historical_backlogs", "Historical backlogs", "number")}
        <label>Placement status<select value={form.placement_status} onChange={(event) => setForm({ ...form, placement_status: event.target.value })}><option value="seeking">Seeking placement</option><option value="placed">Placed</option><option value="not_seeking">Not seeking</option></select></label>
        <div className="form-actions"><button className="button button-primary" disabled={saving}>{saving ? "Saving…" : editingId === null ? "Create student account" : "Save student details"}</button></div>
      </form>
    </section>}
    <section className="panel"><h2>Registered students ({students.length})</h2>{loading ? <p className="muted" role="status">Loading student records…</p> : <div className="table-wrap"><table><thead><tr><th>Student</th><th>Student ID</th><th>Department / branch</th><th>CGPA</th><th>Action</th></tr></thead><tbody>{students.map((student) => <tr key={student.id}><td>{student.full_name}<small>{student.email}</small></td><td>{student.profile?.student_id || "—"}</td><td>{[student.profile?.department, student.profile?.branch].filter(Boolean).join(" · ") || "—"}</td><td>{student.profile?.cgpa ?? "—"}</td><td><button type="button" className="text-button" onClick={() => startEdit(student)}>Edit details</button></td></tr>)}{!students.length && <tr><td colSpan={5} className="muted">No student accounts have been created.</td></tr>}</tbody></table></div>}</section>
  </div>;
}

export default function AdminStudentsPage() { return <RequireAuth roles={["administrator"]}><AdminStudentsContent /></RequireAuth>; }
