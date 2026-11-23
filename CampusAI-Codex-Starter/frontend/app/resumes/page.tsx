"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { FILE_UPLOADS_ENABLED, RequireAuth, useAuth } from "../lib/api";

type SectionImprovement = { section: string; current_excerpt?: string; recommendation: string; changes_to_make?: string[] };
type AIReview = { summary: string; strengths: string[]; improvement_areas: SectionImprovement[]; provider: string };
type Analysis = { id: number; filename: string; skills: string[]; education: string[]; projects: string[]; experience: string[]; quality_feedback: { section: string; recommendation: string }[]; ai_review?: AIReview | null; role_comparison?: Gap | null; ai_status?: string; privacy?: string };
type Gap = { id?: number; job_title?: string | null; required_skills: string[]; matching_skills: string[]; missing_skills: string[]; roadmap: { skill: string; priority: string; topics: string; project: string; estimated_duration: string }[]; ai_guidance?: { role_summary: string; candidate_alignment: string; resume_changes?: { skill: string; section: string; current_excerpt?: string; change: string }[] } | null; ai_status?: string; method: string };

function ResumeContent() {
  const { api } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [targetRoleFile, setTargetRoleFile] = useState<File | null>(null);
  const [comparisonRoleFile, setComparisonRoleFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [selectedReviewSection, setSelectedReviewSection] = useState("");
  const [targetRoleInformation, setTargetRoleInformation] = useState("");
  const [targetRoleTitle, setTargetRoleTitle] = useState("");
  const [comparisonRoleInformation, setComparisonRoleInformation] = useState("");
  const [comparisonRoleTitle, setComparisonRoleTitle] = useState("");
  const [gap, setGap] = useState<Gap | null>(null);
  const [activeResult, setActiveResult] = useState<"analysis" | "gap">("analysis");
  const [showResult, setShowResult] = useState(false);
  const [busyAction, setBusyAction] = useState<"analyze" | "compare" | null>(null);
  const [analysisTakingLong, setAnalysisTakingLong] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const selectedSectionRef = useRef<HTMLElement>(null);
  const analysisResultRef = useRef<HTMLDivElement>(null);
  const gapResultRef = useRef<HTMLDivElement>(null);
  const sectionSuggestions: SectionImprovement[] = [
    ...(analysis?.ai_review?.improvement_areas ?? []),
    ...(analysis?.role_comparison?.ai_guidance?.resume_changes ?? []).map((item) => ({
      section: item.section, current_excerpt: item.current_excerpt,
      recommendation: `For ${item.skill}: ${item.change}`, changes_to_make: [item.change],
    })),
  ];
  const reviewSections = [...new Set(sectionSuggestions.map((item) => item.section))];
  const selectedSectionSuggestions = sectionSuggestions.filter((item) => item.section === selectedReviewSection);
  const sectionKey = selectedReviewSection.toLocaleLowerCase();
  const extractedSectionContent = sectionKey.includes("skill") || sectionKey.includes("technical")
    ? analysis?.skills ?? []
    : sectionKey.includes("education") ? analysis?.education ?? []
      : sectionKey.includes("project") ? analysis?.projects ?? []
        : sectionKey.includes("experience") || sectionKey.includes("employment") ? analysis?.experience ?? []
          : [];
  const selectedSectionContent = extractedSectionContent.length
    ? extractedSectionContent
    : [...new Set(selectedSectionSuggestions.map((item) => item.current_excerpt?.trim()).filter((item): item is string => Boolean(item)))];
  useEffect(() => {
    if (showResult && activeResult === "analysis" && analysis) {
      (selectedReviewSection ? selectedSectionRef.current : analysisResultRef.current)?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (showResult && activeResult === "gap" && gap) {
      gapResultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [showResult, activeResult, selectedReviewSection, analysis, gap]);
  async function analyze(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    if (!targetRoleTitle.trim()) { setError("Enter a target role title."); return; }
    if (targetRoleInformation.trim() && targetRoleInformation.trim().length < 20) { setError("Role information must contain at least 20 characters when provided."); return; }
    setBusyAction("analyze"); setAnalysisTakingLong(false); setError(""); setNotice("");
    const slowTimer = setTimeout(() => setAnalysisTakingLong(true), 12_000);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("job_title", targetRoleTitle.trim());
      if (targetRoleFile) form.append("role_file", targetRoleFile);
      else if (targetRoleInformation.trim()) form.append("job_description", targetRoleInformation.trim());
      const result = await api<Analysis>("/api/v1/resumes/analyze", { method: "POST", body: form });
      setAnalysis(result); setGap(null); setActiveResult("analysis");
      setSelectedReviewSection(result.ai_review?.improvement_areas[0]?.section ?? "");
      setShowResult(true); setNotice("Resume and role analysis complete.");
    } catch (cause) {
      setShowResult(false);
      setError(cause instanceof Error ? cause.message : "Resume analysis could not be completed. Please try again.");
    } finally {
      clearTimeout(slowTimer);
      setAnalysisTakingLong(false);
      setBusyAction(null);
    }
  }
  async function compare(event: FormEvent) {
    event.preventDefault(); setError(""); setNotice(""); setBusyAction("compare");
    try {
      if (!analysis) throw new Error("Analyze a resume first. It will be reused for this comparison.");
      if (!comparisonRoleTitle.trim()) throw new Error("Enter a role title.");
      if (comparisonRoleFile && comparisonRoleInformation.trim()) throw new Error("Paste role details or upload a role PDF, not both.");
      if (!comparisonRoleFile && comparisonRoleInformation.trim() && comparisonRoleInformation.trim().length < 20) throw new Error("Role information must contain at least 20 characters when provided.");
      const form = new FormData();
      form.append("resume_analysis_id", String(analysis.id));
      form.append("job_title", comparisonRoleTitle.trim());
      if (file) form.append("resume_file", file);
      if (comparisonRoleFile) form.append("role_file", comparisonRoleFile);
      else if (comparisonRoleInformation.trim()) form.append("job_description", comparisonRoleInformation.trim());
      const result = await api<Gap>("/api/v1/resumes/skill-gap/compare", { method: "POST", body: form });
      setGap(result);
      setActiveResult("gap");
      setShowResult(true);
    }
    catch (cause) { setActiveResult(gap ? "gap" : "analysis"); setError(cause instanceof Error ? cause.message : "Skill comparison failed"); }
    finally { setBusyAction(null); }
  }
  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">CAREER TOOLS</p><h1>Resume & skill gaps</h1><p className="muted">Analyze the resume against a target role and receive section-specific edits and skill matches.</p></div></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}{notice && <div className="notice notice-success" role="status">{notice}</div>}
    {!showResult && <div className="result-switcher" role="group" aria-label="Resume tools"><button type="button" className={activeResult === "analysis" ? "button button-primary" : "button button-secondary"} aria-pressed={activeResult === "analysis"} onClick={() => setActiveResult("analysis")}>Resume Analysis</button><button type="button" className={activeResult === "gap" ? "button button-primary" : "button button-secondary"} aria-pressed={activeResult === "gap"} onClick={() => setActiveResult("gap")}>Skill Gap Matching</button></div>}
    <section className="resume-tool-page">
      {activeResult === "analysis" && <div className="panel">{showResult && <button type="button" className="button button-quiet back-to-tools" onClick={() => setShowResult(false)} aria-label="Back to resume tools">{"\u2190"} Back to tools</button>}{!showResult && <> <p className="eyebrow">RESUME ANALYSIS</p><h2>Analyze a resume for a role</h2><p className="muted">Upload the resume and provide the target role together. The extracted resume text and role details are reviewed in the same AI request; common email and phone details are redacted first. Only the structured results are stored. This does not generate an ATS score or predict hiring.</p> </>}
        
        {showResult && analysis && activeResult === "analysis" && <div ref={analysisResultRef} className="analysis-result"><h3>{analysis.filename}</h3>
          <><h3>Resume review</h3><p>{analysis.ai_review?.summary}</p><div><strong>Strengths</strong>{analysis.ai_review?.strengths.length ? <ul>{analysis.ai_review.strengths.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="muted">No strengths returned.</p>}</div></>
          <section className="resume-section-guidance"><h3>Choose a resume section to improve</h3><label>Resume section<select value={selectedReviewSection} onChange={(event) => setSelectedReviewSection(event.target.value)}><option value="">Select a section</option>{reviewSections.map((section) => <option key={section} value={section}>{section}</option>)}</select></label>{!selectedReviewSection && <p className="muted">Select a section to view its resume content and suggested changes below.</p>}</section>
          {selectedReviewSection && <section ref={selectedSectionRef} className="selected-resume-section" aria-live="polite"><p className="eyebrow">SELECTED RESUME SECTION</p><h2>{selectedReviewSection}</h2><h3>Content from your resume</h3>{selectedSectionContent.length ? <ul>{selectedSectionContent.map((item, index) => <li key={`${selectedReviewSection}-${index}`}>{item}</li>)}</ul> : <p className="muted">No extracted text was returned for this section.</p>}<h3>Suggested changes for this section</h3>{selectedSectionSuggestions.length ? selectedSectionSuggestions.map((item, index) => <article className="roadmap-card" key={`${item.section}-${index}`}><p><strong>Review note:</strong> {item.recommendation}</p>{item.current_excerpt && <p className="resume-excerpt"><strong>Text from this section</strong><br />“{item.current_excerpt}”</p>}{item.changes_to_make?.length ? <><strong>Changes to make</strong><ul>{item.changes_to_make.map((change, changeIndex) => <li key={changeIndex}>{change}</li>)}</ul></> : <p className="muted">No section-specific edits were returned for this item.</p>}</article>) : <p className="muted">No suggested changes were returned for this section.</p>}</section>}
          <h3>Skills identified</h3><div className="tag-row">{analysis.skills.map((skill) => <span className="tag" key={skill}>{skill}</span>)}{!analysis.skills.length && <span className="muted">No skills were identified in the resume.</span>}</div><h3>Resume sections</h3><div className="result-columns resume-sections"><div><strong>Education</strong>{analysis.education.length ? <ul>{analysis.education.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="muted">No education entry detected.</p>}</div><div><strong>Projects</strong>{analysis.projects.length ? <ul>{analysis.projects.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="muted">No project entry detected.</p>}</div><div><strong>Experience</strong>{analysis.experience.length ? <ul>{analysis.experience.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="muted">No experience entry detected.</p>}</div></div><p className="muted resume-privacy">{analysis.privacy}</p></div>}
        {FILE_UPLOADS_ENABLED ? <form hidden={showResult} className="form-stack" onSubmit={analyze}><label>Resume file<input type="file" accept=".pdf,.docx,.txt" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label><label>Target role title<input maxLength={180} required value={targetRoleTitle} onChange={(e) => setTargetRoleTitle(e.target.value)} placeholder="e.g. Data Engineer" /></label><label>Target role information (optional)<textarea maxLength={12000} rows={7} value={targetRoleInformation} onChange={(e) => { const value = e.target.value; setTargetRoleInformation(value); if (value.trim()) setTargetRoleFile(null); }} placeholder="Optional: paste role responsibilities and required skills…" /></label><label>Or upload a role specification PDF (optional)<input type="file" accept=".pdf,application/pdf" onChange={(e) => { const selected = e.target.files?.[0] ?? null; setTargetRoleFile(selected); if (selected) setTargetRoleInformation(""); }} /></label><button type="submit" className="button button-primary" disabled={!file || !targetRoleTitle.trim() || busyAction !== null}>{busyAction === "analyze" ? analysisTakingLong ? "AI review is taking longer…" : "Analyzing…" : "Analyze resume and role"}</button>{busyAction === "analyze" && <p className="muted" role="status">Your resume is being extracted and reviewed with AI. Please keep this page open; a clear error will appear if the review cannot be completed.</p>}</form> : <p className="notice notice-info">Resume analysis is disabled on this deployment until malware scanning is configured. Your resume file is not accepted or stored by this service. Ask the administrator to enable uploads only after a scanner is available.</p>}
      </div>}
      {activeResult === "gap" && <div className="panel">{showResult && <button type="button" className="button button-quiet back-to-tools" onClick={() => setShowResult(false)} aria-label="Back to resume tools">{"\u2190"} Back to tools</button>}{!showResult && <> <p className="eyebrow">ROLE MATCHING</p><h2>Compare skills with another role</h2><p className="muted">The role you provided above is compared as part of the resume analysis. You can compare the same AI-extracted resume sections with another role here without uploading the resume again.</p> </>}
        {!analysis && <p className="notice notice-info">{FILE_UPLOADS_ENABLED ? "Select Resume Analysis and upload a resume before comparing it with a role." : "Resume-based skill comparison is unavailable because resume uploads are disabled on this deployment until malware scanning is configured."}</p>}
        
        {showResult && gap && activeResult === "gap" && <div ref={gapResultRef} className="analysis-result"><p className="muted">{gap.job_title ? `Saved comparison: ${gap.job_title}` : "Latest saved role comparison"}</p><h3>Required role skills ({gap.required_skills.length})</h3><div className="tag-row">{gap.required_skills.map((x) => <span className="tag" key={x}>{x}</span>)}{!gap.required_skills.length && <span className="muted">No required skills were identified in the role.</span>}</div><div className="skill-gap-columns"><section><h3>Matching skills ({gap.matching_skills.length})</h3><div className="tag-row">{gap.matching_skills.map((x) => <span className="tag tag-green" key={x}>{x}</span>)}{!gap.matching_skills.length && <span className="muted">No matching skills were identified.</span>}</div></section><section><h3>Skills to develop ({gap.missing_skills.length})</h3><div className="tag-row">{gap.missing_skills.map((x) => <span className="tag tag-amber" key={x}>{x}</span>)}{!gap.missing_skills.length && <span className="muted">No missing skills were identified.</span>}</div></section></div>{gap.ai_guidance ? <><h3>Role analysis</h3><p><strong>Role:</strong> {gap.ai_guidance.role_summary}</p><p><strong>Resume alignment:</strong> {gap.ai_guidance.candidate_alignment}</p></> : <p className="notice notice-info">The role analysis could not be loaded. Submit the comparison again to retry.</p>}{gap.roadmap.length ? <><h3>Learning roadmap</h3>{gap.roadmap.map((item) => <article className="roadmap-card" key={item.skill}><div className="section-heading"><strong>{item.skill}</strong><span>{item.priority} priority · {item.estimated_duration}</span></div><p>{item.topics}</p><small>Practice project: {item.project}</small></article>)}</> : null}{gap.ai_guidance?.resume_changes?.length ? <><h3>Resume changes by section</h3>{gap.ai_guidance.resume_changes.map((item, index) => <article className="roadmap-card" key={`${item.skill}-${index}`}><div className="section-heading"><strong>{item.skill}</strong><span>{item.section}</span></div>{item.current_excerpt && <p className="resume-excerpt"><strong>Current resume text</strong><br />“{item.current_excerpt}”</p>}<p>{item.change}</p></article>)}</> : null}<small>{gap.method}</small></div>}
        <form hidden={showResult} className="form-stack" onSubmit={compare}><label>Role title<input maxLength={180} required value={comparisonRoleTitle} onChange={(e) => setComparisonRoleTitle(e.target.value)} placeholder="e.g. Data Engineer" /></label><label>Role information (optional)<textarea maxLength={12000} rows={7} value={comparisonRoleInformation} onChange={(e) => { const value = e.target.value; setComparisonRoleInformation(value); if (value.trim()) setComparisonRoleFile(null); }} placeholder="Paste role responsibilities and required skills…" /></label>{FILE_UPLOADS_ENABLED && <label>Or upload a role specification PDF (optional)<input type="file" accept=".pdf,application/pdf" onChange={(e) => { const selected = e.target.files?.[0] ?? null; setComparisonRoleFile(selected); if (selected) setComparisonRoleInformation(""); }} /></label>}<button type="submit" className="button button-secondary" disabled={busyAction !== null || !analysis || !comparisonRoleTitle.trim()}>{busyAction === "compare" ? "Comparing…" : "Find skill gaps"}</button></form>
      </div>}
    </section>
  </div>;
}

export default function ResumesPage() { return <RequireAuth roles={["student"]}><ResumeContent /></RequireAuth>; }

