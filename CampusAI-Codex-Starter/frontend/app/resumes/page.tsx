"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { API_BASE, RequireAuth, useAuth } from "../lib/api";

type SectionImprovement = { section: string; current_excerpt?: string; recommendation: string; changes_to_make?: string[] };
type AIReview = { summary: string; strengths: string[]; improvement_areas: SectionImprovement[]; provider: string };
type Analysis = { id: number; filename: string; skills: string[]; education: string[]; projects: string[]; experience: string[]; quality_feedback: { section: string; recommendation: string }[]; ai_review?: AIReview | null; ai_status?: string; privacy?: string; created_at?: string };
type Gap = { id?: number; resume_analysis_id?: number | null; job_title?: string | null; required_skills: string[]; matching_skills: string[]; missing_skills: string[]; roadmap: { skill: string; priority: string; topics: string; project: string; estimated_duration: string }[]; ai_guidance?: { role_summary: string; candidate_alignment: string; resume_changes?: { skill: string; section: string; current_excerpt?: string; change: string }[] } | null; ai_status?: string; method: string; created_at?: string };

function savedDate(value?: string) {
  if (!value) return "Saved date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Saved date unavailable" : date.toLocaleString();
}

function historyDeleteError(cause: unknown, endpoint: string) {
  if (cause instanceof Error && cause.message === "Not Found") {
    return `The API at ${API_BASE} returned 404 for DELETE ${endpoint}. The running server does not expose this route; confirm its /openapi.json is from the updated CampusAI backend.`;
  }
  return cause instanceof Error ? cause.message : `Could not delete saved results (${endpoint}).`;
}

function ResumeContent() {
  const { api } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [comparisonRoleFile, setComparisonRoleFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analysisHistory, setAnalysisHistory] = useState<Analysis[]>([]);
  const [gapHistory, setGapHistory] = useState<Gap[]>([]);
  const [restoringResults, setRestoringResults] = useState(true);
  const [selectedReviewSection, setSelectedReviewSection] = useState("");
  const [comparisonRoleInformation, setComparisonRoleInformation] = useState("");
  const [comparisonRoleTitle, setComparisonRoleTitle] = useState("");
  const [gap, setGap] = useState<Gap | null>(null);
  const [activeResult, setActiveResult] = useState<"analysis" | "gap">("analysis");
  const [showResult, setShowResult] = useState(false);
  const [showSavedResults, setShowSavedResults] = useState(false);
  const [openedFromHistory, setOpenedFromHistory] = useState(false);
  const [deletingHistoryKey, setDeletingHistoryKey] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<"analyze" | "compare" | null>(null);
  const [analysisTakingLong, setAnalysisTakingLong] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const selectedSectionRef = useRef<HTMLElement>(null);
  const analysisResultRef = useRef<HTMLDivElement>(null);
  const gapResultRef = useRef<HTMLDivElement>(null);
  const sectionSuggestions: SectionImprovement[] = [...(analysis?.ai_review?.improvement_areas ?? [])];
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
    let active = true;
    Promise.allSettled([
      api<Analysis[]>("/api/v1/resumes/history"),
      api<Gap[]>("/api/v1/resumes/skill-gap/history"),
    ]).then(([resumeResult, gapResult]) => {
      if (!active) return;
      const savedAnalyses = resumeResult.status === "fulfilled" ? resumeResult.value : [];
      const savedGaps = gapResult.status === "fulfilled" ? gapResult.value : [];
      setAnalysisHistory(savedAnalyses);
      setGapHistory(savedGaps);
      const latestAnalysis = savedAnalyses[0];
      if (latestAnalysis) {
        setAnalysis(latestAnalysis);
        setGap(null);
        setActiveResult("analysis");
        setSelectedReviewSection(latestAnalysis.ai_review?.improvement_areas[0]?.section ?? "");
        setShowResult(true);
      } else if (savedGaps.length) {
        setGap(savedGaps[0]);
      }
    }).finally(() => { if (active) setRestoringResults(false); });
    return () => { active = false; };
  }, [api]);
  useEffect(() => {
    if (showResult && activeResult === "analysis" && analysis) {
      (selectedReviewSection ? selectedSectionRef.current : analysisResultRef.current)?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (showResult && activeResult === "gap" && gap) {
      gapResultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [showResult, activeResult, selectedReviewSection, analysis, gap]);
  async function analyze(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    setBusyAction("analyze"); setAnalysisTakingLong(false); setError(""); setNotice("");
    const slowTimer = setTimeout(() => setAnalysisTakingLong(true), 12_000);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api<Analysis>("/api/v1/resumes/analyze", { method: "POST", body: form });
      const savedResult = { ...result, created_at: result.created_at ?? new Date().toISOString() };
      setAnalysis(savedResult);
      setAnalysisHistory((current) => [savedResult, ...current.filter((item) => item.id !== savedResult.id)]);
      setGap(null); setActiveResult("analysis");
      setSelectedReviewSection(result.ai_review?.improvement_areas[0]?.section ?? "");
      setShowResult(true); setNotice("Resume analysis complete.");
    } catch (cause) {
      if (analysis) setShowResult(true);
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
      const savedResult = { ...result, resume_analysis_id: result.resume_analysis_id ?? analysis.id, created_at: result.created_at ?? new Date().toISOString() };
      setGap(savedResult);
      setGapHistory((current) => [savedResult, ...current.filter((item) => item.id !== savedResult.id)]);
      setActiveResult("gap");
      setShowResult(true);
    }
    catch (cause) {
      if (gap) { setActiveResult("gap"); setShowResult(true); }
      else if (analysis) { setActiveResult("analysis"); setShowResult(true); }
      setError(cause instanceof Error ? cause.message : "Skill comparison failed");
    }
    finally { setBusyAction(null); }
  }
  function openSavedAnalysis(saved: Analysis) {
    setAnalysis(saved);
    setGap(null);
    setActiveResult("analysis");
    setSelectedReviewSection(saved.ai_review?.improvement_areas[0]?.section ?? "");
    setShowResult(true);
    setShowSavedResults(false);
    setOpenedFromHistory(true);
    setError("");
  }
  function openSavedGap(saved: Gap) {
    const linkedResume = analysisHistory.find((item) => item.id === saved.resume_analysis_id);
    if (linkedResume) setAnalysis(linkedResume);
    setGap(saved);
    setActiveResult("gap");
    setShowResult(true);
    setShowSavedResults(false);
    setOpenedFromHistory(true);
    setError("");
  }
  async function deleteSavedAnalysis(saved: Analysis) {
    const endpoint = `/api/v1/resumes/history/${saved.id}`;
    setDeletingHistoryKey(`resume-${saved.id}`); setError("");
    try {
      await api<void>(endpoint, { method: "DELETE" });
      const remaining = analysisHistory.filter((item) => item.id !== saved.id);
      setAnalysisHistory(remaining);
      if (analysis?.id === saved.id) {
        const next = remaining[0] ?? null;
        setAnalysis(next);
        setGap(null);
        setShowResult(Boolean(next)); setOpenedFromHistory(false);
      }
      setNotice("Resume analysis deleted. Related skill comparisons remain in their history.");
    } catch (cause) { setError(historyDeleteError(cause, endpoint)); }
    finally { setDeletingHistoryKey(null); }
  }
  async function deleteSavedGap(saved: Gap) {
    if (saved.id == null) return;
    const endpoint = `/api/v1/resumes/skill-gap/history/${saved.id}`;
    setDeletingHistoryKey(`gap-${saved.id}`); setError("");
    try {
      await api<void>(endpoint, { method: "DELETE" });
      setGapHistory((current) => current.filter((item) => item.id !== saved.id));
      if (gap?.id === saved.id) { setGap(null); setShowResult(false); setOpenedFromHistory(false); }
      setNotice("Skill comparison deleted.");
    } catch (cause) { setError(historyDeleteError(cause, endpoint)); }
    finally { setDeletingHistoryKey(null); }
  }
  async function deleteAllSavedResults() {
    const endpoint = "/api/v1/resumes/history";
    setDeletingHistoryKey("all"); setError("");
    try {
      await api<void>(endpoint, { method: "DELETE" });
      setAnalysisHistory([]); setGapHistory([]); setAnalysis(null); setGap(null);
      setShowResult(false); setOpenedFromHistory(false); setNotice("All saved resume analyses and skill comparisons were deleted.");
    } catch (cause) { setError(historyDeleteError(cause, endpoint)); }
    finally { setDeletingHistoryKey(null); }
  }
  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">CAREER TOOLS</p><h1>Resume & skill gaps</h1><p className="muted">Analyze the resume against a target role and receive section-specific edits and skill matches.</p></div></div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}{notice && <div className="notice notice-success" role="status">{notice}</div>}
    {restoringResults ? <div className="loading-panel" role="status">Loading your saved resume and skill results…</div> : showSavedResults ? <section className="panel saved-results-panel">
      <div className="section-heading"><div><p className="eyebrow">SAVED RESULTS</p><h2>Resume and skill history</h2></div><div className="saved-results-actions"><button type="button" className="button button-quiet" disabled={deletingHistoryKey !== null || (!analysisHistory.length && !gapHistory.length)} onClick={deleteAllSavedResults}>{deletingHistoryKey === "all" ? "Deleting all…" : "Delete all saved results"}</button><button type="button" className="button button-quiet" onClick={() => { setShowSavedResults(false); setShowResult(false); setOpenedFromHistory(false); }}>← Back to analysis</button></div></div>
      <div className="saved-results-columns">
        <section aria-labelledby="saved-resume-heading"><h3 id="saved-resume-heading">Resume analyses</h3>{analysisHistory.length ? analysisHistory.map((item) => <article className="saved-result-entry" key={item.id}><button type="button" className="saved-result-card" onClick={() => openSavedAnalysis(item)}><strong>{item.filename}</strong><span>Resume review</span><small>{savedDate(item.created_at)}</small></button><button type="button" className="button button-quiet saved-result-delete" aria-label={`Delete resume analysis ${item.filename}`} disabled={deletingHistoryKey === `resume-${item.id}`} onClick={() => deleteSavedAnalysis(item)}>{deletingHistoryKey === `resume-${item.id}` ? "Deleting…" : "Delete"}</button></article>) : <p className="muted">No resume analyses saved yet.</p>}</section>
        <section aria-labelledby="saved-skill-heading"><h3 id="saved-skill-heading">Skill comparisons</h3>{gapHistory.length ? gapHistory.map((item, index) => { const linkedResume = analysisHistory.find((resumeItem) => resumeItem.id === item.resume_analysis_id); return <article className="saved-result-entry" key={item.id ?? `${item.job_title}-${index}`}><button type="button" className="saved-result-card" onClick={() => openSavedGap(item)}><strong>{item.job_title || "Role comparison"}</strong><span>{linkedResume?.filename || "Resume details unavailable"}</span><small>{item.matching_skills.length} matching · {item.missing_skills.length} to develop · {savedDate(item.created_at)}</small></button><button type="button" className="button button-quiet saved-result-delete" aria-label={`Delete skill comparison ${item.job_title || "role comparison"}`} disabled={item.id == null || deletingHistoryKey === `gap-${item.id}`} onClick={() => deleteSavedGap(item)}>{deletingHistoryKey === `gap-${item.id}` ? "Deleting…" : "Delete"}</button></article>; }) : <p className="muted">No skill comparisons saved yet.</p>}</section>
      </div>
    </section> : <>
    {showResult && (analysis || (activeResult === "gap" && gap)) && <div className="result-switcher" role="group" aria-label="Saved resume results">{analysis && <button type="button" className={activeResult === "analysis" ? "button button-primary" : "button button-secondary"} aria-pressed={activeResult === "analysis"} onClick={() => setActiveResult("analysis")}>Resume analysis</button>}{gap && <button type="button" className={activeResult === "gap" ? "button button-primary" : "button button-secondary"} aria-pressed={activeResult === "gap"} onClick={() => setActiveResult("gap")}>Skill gap results</button>}<button type="button" className="button button-quiet back-to-tools" onClick={() => { if (openedFromHistory) setShowSavedResults(true); else setShowResult(false); }}>{openedFromHistory ? "← Back to saved results" : "← Back to analysis"}</button><button type="button" className="button button-quiet" onClick={() => setShowSavedResults(true)}>View saved results</button></div>}
    {!showResult && <div className="result-switcher" role="group" aria-label="Resume tools"><button type="button" className={activeResult === "analysis" ? "button button-primary" : "button button-secondary"} aria-pressed={activeResult === "analysis"} onClick={() => setActiveResult("analysis")}>Resume Analysis</button><button type="button" className={activeResult === "gap" ? "button button-primary" : "button button-secondary"} aria-pressed={activeResult === "gap"} onClick={() => setActiveResult("gap")}>Skill Gap Matching</button>{(analysisHistory.length > 0 || gapHistory.length > 0) && <button type="button" className="button button-quiet" onClick={() => setShowSavedResults(true)}>View saved results</button>}</div>}
    <section className="resume-tool-page">
      {activeResult === "analysis" && <div className="panel">{!showResult && <> <p className="eyebrow">RESUME ANALYSIS</p><h2>Analyze a resume</h2><p className="muted">Upload a resume to get a review of its content, strengths, and suggested improvements. Resume analysis and role skill matching run separately. Common email and phone details are redacted before AI review; only structured results are stored. This does not generate an ATS score or predict hiring.</p> </>}
        
        {showResult && analysis && activeResult === "analysis" && <div ref={analysisResultRef} className="analysis-result"><h3>{analysis.filename}</h3>
          <><h3>Resume review</h3><p>{analysis.ai_review?.summary}</p><div><strong>Strengths</strong>{analysis.ai_review?.strengths.length ? <ul>{analysis.ai_review.strengths.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p className="muted">No strengths returned.</p>}</div></>
          <section className="resume-section-guidance"><h3>Choose a resume section to improve</h3><label>Resume section<select value={selectedReviewSection} onChange={(event) => setSelectedReviewSection(event.target.value)}><option value="">Select a section</option>{reviewSections.map((section) => <option key={section} value={section}>{section}</option>)}</select></label>{!selectedReviewSection && <p className="muted">Select a section to view its resume content and suggested changes below.</p>}</section>
          {selectedReviewSection && <section ref={selectedSectionRef} className="selected-resume-section" aria-live="polite"><p className="eyebrow">SELECTED RESUME SECTION</p><h2>{selectedReviewSection}</h2><h3>Content from your resume</h3>{selectedSectionContent.length ? <ul>{selectedSectionContent.map((item, index) => <li key={`${selectedReviewSection}-${index}`}>{item}</li>)}</ul> : <p className="muted">No extracted text was returned for this section.</p>}<h3>Suggested changes for this section</h3>{selectedSectionSuggestions.length ? selectedSectionSuggestions.map((item, index) => <article className="roadmap-card" key={`${item.section}-${index}`}><p><strong>Review note:</strong> {item.recommendation}</p>{item.current_excerpt && <p className="resume-excerpt"><strong>Text from this section</strong><br />“{item.current_excerpt}”</p>}{item.changes_to_make?.length ? <><strong>Changes to make</strong><ul>{item.changes_to_make.map((change, changeIndex) => <li key={changeIndex}>{change}</li>)}</ul></> : <p className="muted">No section-specific edits were returned for this item.</p>}</article>) : <p className="muted">No suggested changes were returned for this section.</p>}</section>}
          <h3>Skills identified</h3><div className="tag-row">{analysis.skills.map((skill) => <span className="tag" key={skill}>{skill}</span>)}{!analysis.skills.length && <span className="muted">No skills were identified in the resume.</span>}</div><h3>Resume sections</h3><div className="result-columns resume-sections"><div><strong>Education</strong>{analysis.education.length ? <ul>{analysis.education.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="muted">No education entry detected.</p>}</div><div><strong>Projects</strong>{analysis.projects.length ? <ul>{analysis.projects.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="muted">No project entry detected.</p>}</div><div><strong>Experience</strong>{analysis.experience.length ? <ul>{analysis.experience.map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="muted">No experience entry detected.</p>}</div></div><p className="muted resume-privacy">{analysis.privacy}</p></div>}
        <form hidden={showResult} className="form-stack" onSubmit={analyze}><label>Resume file<input type="file" accept=".pdf,.docx,.txt" required onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label><button type="submit" className="button button-primary" disabled={!file || busyAction !== null}>{busyAction === "analyze" ? analysisTakingLong ? "AI review is taking longer…" : "Analyzing…" : "Analyze resume"}</button>{busyAction === "analyze" && <p className="muted" role="status">Your resume is being extracted and reviewed with AI. Please keep this page open; a clear error will appear if the review cannot be completed.</p>}</form>
      </div>}
      {activeResult === "gap" && <div className="panel">{!showResult && <> <p className="eyebrow">ROLE MATCHING</p><h2>Find skill gaps for a role</h2><p className="muted">Compare the AI-extracted sections from your saved resume analysis with a target role. This creates a separate skill comparison and does not rerun the resume review.</p> </>}
        {!analysis && <p className="notice notice-info">Select Resume Analysis and upload a resume before comparing it with a role.</p>}
        
        {showResult && gap && activeResult === "gap" && <div ref={gapResultRef} className="analysis-result"><p className="muted">{gap.job_title ? `Saved comparison: ${gap.job_title}` : "Latest saved role comparison"}</p><h3>Required role skills ({gap.required_skills.length})</h3><div className="tag-row">{gap.required_skills.map((x) => <span className="tag" key={x}>{x}</span>)}{!gap.required_skills.length && <span className="muted">No required skills were identified in the role.</span>}</div><div className="skill-gap-columns"><section><h3>Matching skills ({gap.matching_skills.length})</h3><div className="tag-row">{gap.matching_skills.map((x) => <span className="tag tag-green" key={x}>{x}</span>)}{!gap.matching_skills.length && <span className="muted">No matching skills were identified.</span>}</div></section><section><h3>Skills to develop ({gap.missing_skills.length})</h3><div className="tag-row">{gap.missing_skills.map((x) => <span className="tag tag-amber" key={x}>{x}</span>)}{!gap.missing_skills.length && <span className="muted">No missing skills were identified.</span>}</div></section></div>{gap.ai_guidance ? <><h3>Role analysis</h3><p><strong>Role:</strong> {gap.ai_guidance.role_summary}</p><p><strong>Resume alignment:</strong> {gap.ai_guidance.candidate_alignment}</p></> : <p className="notice notice-info">The role analysis could not be loaded. Submit the comparison again to retry.</p>}{gap.roadmap.length ? <><h3>Learning roadmap</h3>{gap.roadmap.map((item) => <article className="roadmap-card" key={item.skill}><div className="section-heading"><strong>{item.skill}</strong><span>{item.priority} priority · {item.estimated_duration}</span></div><p>{item.topics}</p><small>Practice project: {item.project}</small></article>)}</> : null}{gap.ai_guidance?.resume_changes?.length ? <><h3>Resume changes by section</h3>{gap.ai_guidance.resume_changes.map((item, index) => <article className="roadmap-card" key={`${item.skill}-${index}`}><div className="section-heading"><strong>{item.skill}</strong><span>{item.section}</span></div>{item.current_excerpt && <p className="resume-excerpt"><strong>Current resume text</strong><br />“{item.current_excerpt}”</p>}<p>{item.change}</p></article>)}</> : null}<small>{gap.method}</small></div>}
        <form hidden={showResult} className="form-stack" onSubmit={compare}><label>Role title<input maxLength={180} required value={comparisonRoleTitle} onChange={(e) => setComparisonRoleTitle(e.target.value)} placeholder="e.g. Data Engineer" /></label><label>Role information (optional)<textarea maxLength={12000} rows={7} value={comparisonRoleInformation} onChange={(e) => { const value = e.target.value; setComparisonRoleInformation(value); if (value.trim()) setComparisonRoleFile(null); }} placeholder="Paste role responsibilities and required skills…" /></label><label>Or upload a role specification PDF (optional)<input type="file" accept=".pdf,application/pdf" onChange={(e) => { const selected = e.target.files?.[0] ?? null; setComparisonRoleFile(selected); if (selected) setComparisonRoleInformation(""); }} /></label><button type="submit" className="button button-secondary" disabled={busyAction !== null || !analysis || !comparisonRoleTitle.trim()}>{busyAction === "compare" ? "Comparing…" : "Find skill gaps"}</button></form>
      </div>}
    </section>
    </>}
  </div>;
}

export default function ResumesPage() { return <RequireAuth roles={["student"]}><ResumeContent /></RequireAuth>; }

