"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../../../../lib/api";

type Company = { id: number; name: string; industry: string | null };
type Student = { id: number; full_name: string; email: string };
type Application = { id: number; student_user_id: number; company_id: number; role: string; status: string };
type CompanyStudent = Student & { applications: Application[] };

function CompanyStudentsContent() {
  const { api } = useAuth();
  const params = useParams<{ companyId: string }>();
  const companyId = Number(params.companyId);
  const [company, setCompany] = useState<Company | null>(null);
  const [students, setStudents] = useState<CompanyStudent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!Number.isInteger(companyId) || companyId < 1) {
      setError("Company not found.");
      setLoading(false);
      return;
    }
    Promise.all([
      api<Company[]>("/api/v1/companies/"),
      api<Student[]>("/api/v1/students/"),
      api<Application[]>("/api/v1/admin/applications"),
    ]).then(([companies, registeredStudents, applications]) => {
      const selectedCompany = companies.find((item) => item.id === companyId);
      if (!selectedCompany) {
        setError("Company not found.");
        return;
      }
      setCompany(selectedCompany);
      const byStudent = new Map<number, CompanyStudent>();
      for (const application of applications.filter((row) => row.company_id === companyId)) {
        const student = registeredStudents.find((item) => item.id === application.student_user_id);
        if (!student) continue;
        const existing = byStudent.get(student.id);
        if (existing) existing.applications.push(application);
        else byStudent.set(student.id, { ...student, applications: [application] });
      }
      setStudents([...byStudent.values()].sort((a, b) => a.full_name.localeCompare(b.full_name)));
    }).catch((cause) => {
      setError(cause instanceof Error ? cause.message : "Could not load company students.");
    }).finally(() => setLoading(false));
  }, [api, companyId]);

  return <div className="stack-xl">
    <a href="/admin" className="button button-quiet back-to-tools" aria-label="Back to admin dashboard">{"\u2190"} Back to admin</a>
    <div className="page-heading"><div><p className="eyebrow">COMPANY STUDENTS</p><h1>{company?.name ?? "Company students"}</h1><p className="muted">Students with applications to this company’s placement drives.</p></div></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    {loading ? <p className="muted" role="status">Loading company students…</p> : company && <section className="panel">
      <h2>Registered students ({students.length})</h2>
      {students.length ? <div className="table-wrap"><table><thead><tr><th>Student</th><th>Email</th><th>Applied roles and status</th></tr></thead><tbody>
        {students.map((student) => <tr key={student.id}><td>{student.full_name}</td><td>{student.email}</td><td><ul>{student.applications.map((application) => <li key={application.id}>{application.role} · {application.status}</li>)}</ul></td></tr>)}
      </tbody></table></div> : <p className="empty-state">No students have applied to this company’s placement drives yet.</p>}
    </section>}
  </div>;
}

export default function CompanyStudentsPage() {
  return <RequireAuth roles={["administrator", "placement_officer"]}><CompanyStudentsContent /></RequireAuth>;
}
