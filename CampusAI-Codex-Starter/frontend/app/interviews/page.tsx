"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { RequireAuth, useAuth } from "../lib/api";

type QuestionOption = { id: string; text: string };
type Session = { id: number; category: string; language: string; question: string; question_type: "typed" | "multiple_choice"; options: QuestionOption[]; focus: string | null; status?: string; generation_mode: string; language_note: string | null; question_limit: number };
type PracticeResult = { question: string; answer: string; score: number; feedback: { strengths?: string[]; improvements?: string[]; assessment_note?: string; options?: QuestionOption[]; correct_option?: string; correct_text?: string; selected_option?: string; correct_answer?: string } };
type PracticeReview = { id: number; status: string; completed: boolean; answered_count: number; question_limit: number; question_type?: "typed" | "multiple_choice"; correct_count?: number | null; average_score: number | null; results: PracticeResult[] };
type AnswerSaved = PracticeReview & { question?: string | null; options?: QuestionOption[]; question_type?: "typed" | "multiple_choice"; generation_mode?: string };
type InterviewSummary = { id: number; category: string; language: string; focus: string | null; question_type: "typed" | "multiple_choice"; status: string; response_count: number; question_limit: number; average_score: number | null; created_at: string };
type HistoryDetail = { id: number; category: string; language: string; focus: string | null; question_type: "typed" | "multiple_choice"; status: string; average_score: number | null; answered_count: number; results: PracticeResult[] };
type StructuredAnswer = { short_answer: string; explanation: string; key_points: string[]; next_question: string };
type DoubtMessage = { question: string; answer: StructuredAnswer | null; status: "pending" | "answered" | "failed" };
const clean = (value: string) => value.replace(/\*\*/g, "");

function InterviewPrompt({ question, coding = false }: { question: string; coding?: boolean }) {
  const marker = /\n\s*CODE_SNIPPET(?:\s*\(([^)]+)\))?:\s*\n/i;
  const parts = coding ? question.split(marker) : [];
  if (coding && parts.length >= 2) {
    const language = question.match(marker)?.[1] ?? "Code";
    return <div className="interview-prompt"><h1>{clean(parts[0])}</h1><div className="interview-code-block"><span>{clean(language)}</span><pre><code>{clean(parts[parts.length - 1])}</code></pre></div></div>;
  }
  return <h1 className={coding ? "interview-coding-prompt" : undefined}>{clean(question)}</h1>;
}

function InterviewsContent() {
  const { api } = useAuth();
  const [mode, setMode] = useState<"prepare" | "ask">("prepare");
  const [category, setCategory] = useState("technical");
  const [questionType, setQuestionType] = useState<"typed" | "multiple_choice">("typed");
  const [language, setLanguage] = useState("en");
  const [focus, setFocus] = useState("");
  const [questionLimit, setQuestionLimit] = useState(5);
  const [session, setSession] = useState<Session | null>(null);
  const [questions, setQuestions] = useState<Session[]>([]);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [typedAnswers, setTypedAnswers] = useState<string[]>([]);
  const [optionAnswers, setOptionAnswers] = useState<string[]>([]);
  const [answeredCount, setAnsweredCount] = useState(0);
  const [practiceReview, setPracticeReview] = useState<PracticeReview | null>(null);
  const [history, setHistory] = useState<InterviewSummary[]>([]);
  const [historyDetail, setHistoryDetail] = useState<HistoryDetail | null>(null);
  const [doubt, setDoubt] = useState("");
  const [doubtMessages, setDoubtMessages] = useState<DoubtMessage[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadHistory = useCallback(async () => setHistory(await api<InterviewSummary[]>("/api/v1/interviews/history")), [api]);
  useEffect(() => { void loadHistory().catch(() => setError("Practice history could not be loaded.")); }, [loadHistory]);

  async function start() {
    setBusy(true); setError(""); setPracticeReview(null); setAnsweredCount(0); setQuestions([]); setQuestionIndex(0); setTypedAnswers([]); setOptionAnswers([]);
    try {
      const created = await api<Session>("/api/v1/interviews/sessions", { method: "POST", body: JSON.stringify({ category, language, focus: focus.trim() || null, question_type: questionType, question_limit: questionLimit }) });
      setSession(created); setQuestions([created]); void loadHistory().catch(() => setError("Practice history could not be refreshed."));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start practice"); }
    finally { setBusy(false); }
  }
  const currentQuestion = questions[questionIndex];
  const currentTypedAnswer = typedAnswers[questionIndex] ?? "";
  const currentOptionAnswer = optionAnswers[questionIndex] ?? "";
  const finalQuestion = !!session && questionIndex === session.question_limit - 1;
  function setCurrentTypedAnswer(value: string) {
    setTypedAnswers((items) => { const next = [...items]; next[questionIndex] = value; return next; });
  }
  function setCurrentOptionAnswer(value: string) {
    setOptionAnswers((items) => { const next = [...items]; next[questionIndex] = value; return next; });
  }
  async function saveCurrentAnswer(): Promise<AnswerSaved | null> {
    if (!session || !currentQuestion) return null;
    const submittedAnswer = currentQuestion.question_type === "multiple_choice" ? currentOptionAnswer : currentTypedAnswer;
    if (!submittedAnswer.trim()) return null;
    setBusy(true); setError("");
    try {
      const result = await api<AnswerSaved>(`/api/v1/interviews/sessions/${session.id}/responses`, { method: "POST", body: JSON.stringify({ question: currentQuestion.question, answer: submittedAnswer }) });
      setAnsweredCount(result.answered_count);
      if (result.completed) { setPracticeReview(result); setSession(null); }
      if (result.completed) await loadHistory();
      return result;
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not submit answer"); }
    finally { setBusy(false); }
    return null;
  }
  async function goPrevious() {
    if (questionIndex > 0) setQuestionIndex((index) => index - 1);
  }
  async function goNext() {
    if (!session || !currentQuestion || finalQuestion) return;
    if (questionIndex < answeredCount) {
      if (questionIndex + 1 < questions.length) { setQuestionIndex((index) => index + 1); return; }
      setBusy(true); setError("");
      try {
        const next = await api<Omit<Session, "id" | "category" | "language" | "focus">>(`/api/v1/interviews/sessions/${session.id}/next-question`, { method: "POST" });
        const nextSession = { ...session, ...next };
        setSession(nextSession); setQuestions((items) => [...items.slice(0, questionIndex + 1), nextSession]); setQuestionIndex((index) => index + 1);
      } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not get another question"); }
      finally { setBusy(false); }
      return;
    }
    if (currentQuestion.question_type === "multiple_choice" ? !currentOptionAnswer : currentTypedAnswer.trim().length < 10) return;
    const result = await saveCurrentAnswer();
    if (!result || result.completed) return;
    if (result.question) {
      const nextSession = { ...session, question: result.question, options: result.options ?? [], question_type: result.question_type ?? session.question_type, generation_mode: result.generation_mode ?? "gemini" };
      setSession(nextSession); setQuestions((items) => [...items.slice(0, questionIndex + 1), nextSession]); setQuestionIndex((index) => index + 1);
      return;
    }
    setBusy(true); setError("");
    try {
      const next = await api<Omit<Session, "id" | "category" | "language" | "focus">>(`/api/v1/interviews/sessions/${session.id}/next-question`, { method: "POST" });
      const nextSession = { ...session, ...next };
      setSession(nextSession); setQuestions((items) => [...items.slice(0, questionIndex + 1), nextSession]); setQuestionIndex((index) => index + 1);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not get another question"); }
    finally { setBusy(false); }
  }
  async function submitFinalAnswer() {
    if (!finalQuestion || (currentQuestion?.question_type === "multiple_choice" ? !currentOptionAnswer : currentTypedAnswer.trim().length < 10)) return;
    await saveCurrentAnswer();
  }
  async function ask(event: FormEvent) {
    event.preventDefault(); if (!doubt.trim() || busy) return;
    const question = doubt.trim();
    const messageIndex = doubtMessages.length;
    setDoubt(""); setBusy(true); setError("");
    setDoubtMessages((items) => [...items, { question, answer: null, status: "pending" }]);
    try {
      const result = await api<{ answer: StructuredAnswer }>("/api/v1/interviews/ask", { method: "POST", body: JSON.stringify({ question, focus: focus.trim() || null, language }) });
      if (!result.answer || typeof result.answer.short_answer !== "string" || typeof result.answer.explanation !== "string") {
        throw new Error("The assistant returned an incomplete answer. Please try again.");
      }
      setDoubtMessages((items) => items.map((item, index) => index === messageIndex ? { ...item, answer: result.answer, status: "answered" } : item));
    } catch (cause) {
      setDoubt(question);
      setDoubtMessages((items) => items.map((item, index) => index === messageIndex ? { ...item, status: "failed" } : item));
      setError(cause instanceof Error ? cause.message : "The assistant could not answer right now");
    }
    finally { setBusy(false); }
  }
  async function viewPractice(id: number) {
    setBusy(true); setError("");
    try { setHistoryDetail(await api<HistoryDetail>(`/api/v1/interviews/history/${id}`)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Practice details could not be loaded"); }
    finally { setBusy(false); }
  }

  if (session && currentQuestion) return <main className="interview-session-screen">
    <header className="interview-session-header"><div><p className="eyebrow">INTERVIEW PRACTICE</p><span className="muted">Question {questionIndex + 1} of {session.question_limit}</span></div>
      {finalQuestion && <button className="button button-primary" onClick={() => void submitFinalAnswer()} disabled={busy || (currentQuestion.question_type === "multiple_choice" ? !currentOptionAnswer : currentTypedAnswer.trim().length < 10)}>{busy ? "Submitting…" : "Submit interview"}</button>}
    </header>
    {error && <div className="notice notice-error" role="alert">{clean(error)}</div>}
    <section className="interview-question-content" aria-live="polite"><InterviewPrompt question={currentQuestion.question} coding={session.category === "coding"} />
      {currentQuestion.question_type === "multiple_choice" ? <fieldset className="interview-options"><legend>Choose one answer</legend>{currentQuestion.options.map((option) => <label className="interview-option" key={option.id}><input type="radio" name="interview-option" value={option.id} checked={currentOptionAnswer === option.id} disabled={questionIndex < answeredCount} onChange={() => setCurrentOptionAnswer(option.id)} /><span><strong>{option.id}.</strong> {clean(option.text)}</span></label>)}</fieldset> : <label className="interview-typed-answer">Your answer<textarea minLength={10} maxLength={8000} rows={9} required disabled={questionIndex < answeredCount} value={currentTypedAnswer} onChange={(event) => setCurrentTypedAnswer(event.target.value)} placeholder="Type your answer here…" /></label>}
    </section>
    <footer className="interview-session-footer"><button className="button button-secondary" onClick={() => void goPrevious()} disabled={busy || questionIndex === 0}>Previous</button>
      <button className="button button-primary" onClick={() => void goNext()} disabled={busy || finalQuestion || questionIndex < answeredCount && questionIndex >= questions.length - 1 || (questionIndex === answeredCount && (currentQuestion.question_type === "multiple_choice" ? !currentOptionAnswer : currentTypedAnswer.trim().length < 10))}>{busy ? "Saving…" : "Next"}</button>
    </footer>
  </main>;

  return <div className="stack-xl">
    <div className="page-heading"><div><p className="eyebrow">PRACTICE STUDIO</p><h1>Interview preparation</h1><p className="muted">Practice role-specific questions or ask about interview topics and doubts.</p></div></div>
    {error && <div className="notice notice-error" role="alert">{clean(error)}</div>}
    <div className="section-heading" role="tablist" aria-label="Interview tools">
      <button className={`button ${mode === "prepare" ? "button-primary" : "button-secondary"}`} role="tab" aria-selected={mode === "prepare"} onClick={() => setMode("prepare")}>Interview preparation</button>
      <button className={`button ${mode === "ask" ? "button-primary" : "button-secondary"}`} role="tab" aria-selected={mode === "ask"} onClick={() => setMode("ask")}>Ask questions and doubts</button>
    </div>

    {mode === "prepare" ? <div className="stack">
      <section className="panel"><p className="eyebrow">GENERATE PRACTICE QUESTIONS</p><h2>Set up your practice</h2><div className="form-stack">
        <label>Interview category<select value={category} onChange={(e) => { const nextCategory = e.target.value; setCategory(nextCategory); if (nextCategory === "coding") setQuestionType("multiple_choice"); }}><option value="technical">Technical</option><option value="hr">HR</option><option value="aptitude">Aptitude</option><option value="coding">Coding</option></select></label>
        <label>Answer format<select value={category === "coding" ? "multiple_choice" : questionType} disabled={category === "coding"} onChange={(e) => setQuestionType(e.target.value as "typed" | "multiple_choice")}><option value="typed">Typed answer</option><option value="multiple_choice">Multiple choice</option></select>{category === "coding" && <span className="field-hint">Coding questions include a code snippet and answer choices.</span>}</label>
        <label>Language<select value={language} onChange={(e) => setLanguage(e.target.value)}><option value="en">English</option><option value="hi">Hindi</option><option value="kn">Kannada</option></select></label>
        <label>Number of questions<input type="number" min={1} max={20} value={questionLimit} onChange={(e) => setQuestionLimit(Math.max(1, Math.min(20, Number(e.target.value) || 1)))} /></label>
        <label>Role or job specification (optional)<textarea maxLength={2000} rows={4} value={focus} onChange={(e) => setFocus(e.target.value)} placeholder="Paste a role title, requirements, or job specification…" /></label>
        <button className="button button-primary" onClick={start} disabled={busy || !!session}>{busy ? "Generating…" : session ? "Session in progress" : "Start interview preparation"}</button>
      </div>
      </section>
      {practiceReview && <section className="panel"><div className="section-heading"><div><p className="eyebrow">PRACTICE RESULTS</p><h2>Your answers and feedback</h2></div><div className="score-display"><strong>{practiceReview.question_type === "multiple_choice" ? `${practiceReview.correct_count ?? 0}/${practiceReview.question_limit}` : practiceReview.average_score ?? "—"}</strong><span>{practiceReview.question_type === "multiple_choice" ? "Correct answers" : "Average score / 5"}</span></div></div>
        {practiceReview.results.length ? <ol className="stack">{practiceReview.results.map((item, index) => <li className="question-card" key={`${index}-${item.question}`}><h3>{index + 1}. {clean(item.question)}</h3><h4>{practiceReview.question_type === "multiple_choice" ? item.score === 1 ? "Correct · 1 point" : "Incorrect · 0 points" : `Your answer · ${item.score}/5`}</h4><p>{clean(item.answer)}</p>{practiceReview.question_type === "typed" && item.feedback.correct_answer && <><h4>Reference answer</h4><p>{clean(item.feedback.correct_answer)}</p></>}{item.feedback.strengths?.length ? <><h4>Strengths</h4><ul>{item.feedback.strengths.map((x, i) => <li key={i}>{clean(x)}</li>)}</ul></> : null}{item.feedback.improvements?.length ? <><h4>Suggestions</h4><ul>{item.feedback.improvements.map((x, i) => <li key={i}>{clean(x)}</li>)}</ul></> : null}{item.feedback.assessment_note && <p className="muted">{clean(item.feedback.assessment_note)}</p>}</li>)}</ol> : <p className="empty-state">No answers were submitted in this practice.</p>}
        <button className="button button-primary" onClick={() => setPracticeReview(null)}>Start new practice</button>
      </section>}
    </div> : <section className="panel"><p className="eyebrow">INTERVIEW Q&amp;A</p><h2>Ask questions and doubts</h2><p className="muted">Ask about concepts, interview answers, or how to prepare for the role/specification below.</p>
      <label>Role or job specification (optional)<textarea maxLength={2000} rows={3} value={focus} onChange={(e) => setFocus(e.target.value)} placeholder="Add context to tailor the answer…" /></label>
      <label>Answer language<select value={language} onChange={(e) => setLanguage(e.target.value)}><option value="en">English</option><option value="hi">Hindi</option><option value="kn">Kannada</option></select></label>
      <div className="chat-messages interview-qa-messages" aria-live="polite">
        {doubtMessages.map((item, index) => (
          <article className="interview-qa-exchange" key={index}>
            <div className="chat-message interview-qa-question"><strong>You</strong><p>{clean(item.question)}</p></div>
            <div className="chat-message interview-qa-answer">
              <strong>Answer</strong>
              {!item.answer && <p role="status">{item.status === "pending" ? "Preparing your answer…" : "An answer could not be loaded. Your question is still here; you can try again below."}</p>}
              {item.answer && <><h4>Short answer</h4><p>{clean(item.answer.short_answer)}</p>
              <h4>Explanation</h4><p>{clean(item.answer.explanation)}</p>
              {(item.answer.key_points ?? []).length > 0 && <><h4>Key points</h4><ul>{item.answer.key_points.map((point, i) => <li key={i}>{clean(point)}</li>)}</ul></>}
              {item.answer.next_question && <div className="interview-next-question"><strong>Possible next interview question</strong><p>{clean(item.answer.next_question)}</p></div>}</>}
            </div>
          </article>
        ))}
      </div>
      <form className="chat-composer" onSubmit={ask}><textarea required minLength={3} maxLength={2000} rows={3} value={doubt} onChange={(e) => setDoubt(e.target.value)} placeholder="Type your interview question or doubt…" /><button className="button button-primary" disabled={busy || doubt.trim().length < 3}>{busy ? "Answering…" : "Ask question"}</button></form>
    </section>}

    <section className="panel"><div className="section-heading"><div><p className="eyebrow">YOUR ACTIVITY</p><h2>Practice history</h2></div><button className="button button-ghost" onClick={() => void loadHistory()} disabled={busy}>Refresh</button></div>
      {history.length ? <div className="table-wrap"><table><thead><tr><th>Started</th><th>Category</th><th>Focus</th><th>Questions</th><th>Score</th><th>Status</th><th>Details</th></tr></thead><tbody>{history.map((item) => <tr key={item.id}><td>{new Date(item.created_at).toLocaleDateString()}</td><td>{item.category}</td><td>{item.focus || "General"}</td><td>{item.response_count}/{item.question_limit}</td><td>{item.average_score === null ? "—" : item.question_type === "multiple_choice" ? `${Math.round(item.average_score * item.response_count)}/${item.response_count} correct` : `${item.average_score}/5 avg.`}</td><td>{item.status}</td><td><button className="button button-ghost" onClick={() => void viewPractice(item.id)} disabled={busy || item.status !== "completed"} aria-label={`View practice session ${item.id}`}>{item.status === "completed" ? "View answers" : "In progress"}</button></td></tr>)}</tbody></table></div> : <div className="empty-state">Completed and active practice sessions will appear here.</div>}
      {historyDetail && <div className="analysis-result"><div className="section-heading"><div><p className="eyebrow">SAVED PRACTICE</p><h3>{historyDetail.category} · {historyDetail.answered_count} questions</h3>{historyDetail.focus && <p className="muted">{clean(historyDetail.focus)}</p>}</div><div className="score-display"><strong>{historyDetail.question_type === "multiple_choice" ? `${historyDetail.results.filter((item) => item.score === 1).length}/${historyDetail.answered_count}` : historyDetail.average_score ?? "—"}</strong><span>{historyDetail.question_type === "multiple_choice" ? "Correct answers" : "Average / 5"}</span></div></div>
        {historyDetail.results.map((item, index) => <article className="question-card" key={`${historyDetail.id}-${index}`}><h4>{index + 1}. {clean(item.question)}</h4>{historyDetail.question_type === "multiple_choice" && item.feedback.options?.length ? <><p><strong>{item.score === 1 ? "Correct · 1 point" : "Incorrect · 0 points"}</strong></p><p><strong>Options</strong></p><ul>{item.feedback.options.map((option) => <li key={option.id}>{option.id}. {clean(option.text)}{option.id === item.feedback.correct_option ? " — Correct answer" : ""}{option.id === item.feedback.selected_option ? " — Your choice" : ""}</li>)}</ul><p><strong>Correct answer:</strong> {item.feedback.correct_option}. {clean(item.feedback.correct_text ?? "")}</p><p><strong>Your answer:</strong> {clean(item.answer)}</p></> : <><p><strong>Your answer:</strong> {clean(item.answer)}</p><p><strong>Score:</strong> {item.score}/5</p>{item.feedback.correct_answer && <p><strong>Reference answer:</strong> {clean(item.feedback.correct_answer)}</p>}</>}{item.feedback.strengths?.length ? <><strong>Strengths</strong><ul>{item.feedback.strengths.map((text, i) => <li key={i}>{clean(text)}</li>)}</ul></> : null}{item.feedback.improvements?.length ? <><strong>Suggestions</strong><ul>{item.feedback.improvements.map((text, i) => <li key={i}>{clean(text)}</li>)}</ul></> : null}</article>)}
      </div>}
    </section>
  </div>;
}

export default function InterviewsPage() { return <RequireAuth roles={["student"]}><InterviewsContent /></RequireAuth>; }
