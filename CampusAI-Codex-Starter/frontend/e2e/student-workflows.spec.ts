import { expect, test } from "@playwright/test";

let e2eCompanyName = "";

test("public landing page reports the local API connection", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /make your next career move with evidence/i })).toBeVisible();
  await expect(page.getByText("Backend API connected", { exact: true })).toBeVisible({ timeout: 10_000 });
});

test("student details returns to dashboard without losing the signed-in session", async ({ page }) => {
  const email = `student-details-nav-${Date.now()}@example.edu`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Student Details Navigation");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/student-details");
  await expect(page.getByRole("heading", { name: "Student details", exact: true })).toBeVisible();
  await page.getByRole("link", { name: /Back to dashboard/ }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Hello, Student" })).toBeVisible();
});

test("interview Q&A keeps the submitted question visible and renders the answer", async ({ page }) => {
  const email = `interview-qa-${Date.now()}@example.edu`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Interview Q&A Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/interviews");
  await page.getByRole("tab", { name: "Ask questions and doubts" }).click();
  await page.route("**/api/v1/interviews/ask", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 700));
    await route.fulfill({ json: { answer: {
      short_answer: "Time complexity describes how an algorithm's work grows with input size.",
      explanation: "It describes how the number of operations changes as input size grows.", key_points: ["It is commonly expressed with Big O notation."],
      next_question: "How would you compare O(n) with O(n²)?",
    }, generation_mode: "assistant" } });
  });
  const question = "What does time complexity mean?";
  await page.locator(".chat-composer textarea").fill(question);
  await page.getByRole("button", { name: "Ask question" }).click();
  await expect(page.getByText(question, { exact: true })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Preparing your answer" })).toBeVisible();
  const questionBubble = page.locator(".interview-qa-question");
  const answerBubble = page.locator(".interview-qa-answer");
  await expect(page.getByText("Time complexity describes how an algorithm's work grows with input size.")).toBeVisible();
  await expect(page.getByText("How would you compare O(n) with O(n²)?")).toBeVisible();
  await expect(questionBubble).toHaveCSS("background-color", "rgb(239, 246, 255)");
  await expect(answerBubble).toHaveCSS("background-color", "rgb(240, 249, 242)");
  const questionBox = await questionBubble.boundingBox();
  const answerBox = await answerBubble.boundingBox();
  expect(questionBox).not.toBeNull();
  expect(answerBox).not.toBeNull();
  expect(answerBox!.x).toBeLessThan(questionBox!.x);
  expect(questionBox!.width).toBeLessThan((await page.evaluate(() => window.innerWidth)) * 0.86);
});

test("coding practice displays only a short code question and selectable choices", async ({ page }) => {
  const email = `coding-mcq-${Date.now()}@example.edu`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Coding Practice Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/interviews");
  await expect(page.getByLabel("Interview category")).toHaveValue("aptitude");
  await expect(page.getByLabel("Answer format")).toHaveValue("multiple_choice");
  await page.route("**/api/v1/interviews/sessions", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({ json: {
      id: 123, category: "coding", language: "en", focus: null,
      question: "What does this print?\n\nCODE_SNIPPET (Python):\nprint(2 + 3)",
      question_type: "multiple_choice", options: [
        { id: "A", text: "23" }, { id: "B", text: "5" }, { id: "C", text: "2 + 3" }, { id: "D", text: "Error" },
      ], generation_mode: "gemini", language_note: null, question_limit: 1,
    } });
  });
  await page.getByLabel("Interview category").selectOption("coding");
  await expect(page.getByLabel("Answer format")).toBeDisabled();
  await page.getByRole("button", { name: "Start interview preparation" }).click();
  await expect(page.getByRole("heading", { name: "What does this print?" })).toBeVisible();
  await expect(page.locator(".interview-code-block code")).toHaveText("print(2 + 3)");
  await expect(page.getByRole("radio", { name: /B\. 5/ })).toBeVisible();
  await expect(page.getByLabel("Your answer")).toHaveCount(0);
});

test("student registers, completes multi-round practice, and sees private history", async ({ page }) => {
  const email = `practice-${Date.now()}@example.edu`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Practice Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.reload();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Hello, E2E" })).toBeVisible();

  await page.goto("/interviews");
  await expect(page.getByRole("heading", { name: "Interview preparation" })).toBeVisible();
  await page.getByLabel("Interview category").selectOption("technical");
  await page.getByLabel("Answer format").selectOption("typed");
  await page.getByLabel("Number of questions").fill("2");
  await page.getByLabel("Role or job specification (optional)").fill("backend developer");
  await page.getByRole("button", { name: "Start interview preparation" }).click();
  const question = page.locator(".interview-question-content > h1");
  await expect(question).toBeVisible();
  const firstQuestion = await question.innerText();
  await expect(page.getByRole("button", { name: "Previous" })).toBeDisabled();

  const response = "I tested the approach with examples, measured the result, and documented the tradeoff for my team.";
  await page.getByLabel("Your answer").fill(response);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(question).not.toHaveText(firstQuestion);
  await expect(page.getByRole("button", { name: "Previous" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Submit interview" })).toBeVisible();
  await page.getByLabel("Your answer").fill("First I compared the options, then I tested edge cases and recorded a measurable result.");
  await page.getByRole("button", { name: "Submit interview" }).click();
  await expect(page.getByRole("heading", { name: "Your answers and feedback" })).toBeVisible();
  await expect(page.getByText("Average score / 5")).toBeVisible();

  const historyRow = page.getByRole("row").filter({ hasText: "backend developer" });
  await expect(historyRow).toContainText("technical");
  await expect(historyRow).toContainText("2");
  await expect(historyRow).toContainText("completed");
  await historyRow.getByRole("button", { name: /View practice session/ }).click();
  await expect(page.getByText(response).first()).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await historyRow.getByRole("button", { name: /Delete practice session/ }).click();
  await expect(page.getByRole("status")).toContainText("Practice history deleted");
  await expect(historyRow).toHaveCount(0);

  await page.goto("/resumes");
  let compareCalls = 0;
  let analyzeCalls = 0;
  await page.route("**/api/v1/resumes/analyze", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    analyzeCalls += 1;
    await new Promise((resolve) => setTimeout(resolve, 400));
    return route.fulfill({ json: {
      id: 991, filename: "e2e-resume.txt", skills: ["python", "sql"], education: ["B.Tech 2027"],
      projects: ["Built a Python data analysis service."], experience: [], quality_feedback: [], ai_status: "complete",
      ai_review: { summary: "A student with Python and SQL skills and a data analysis project.", strengths: ["Built a data analysis service."],
        improvement_areas: [{ section: "Projects", current_excerpt: "Built a Python data analysis service.", recommendation: "Clarify the outcome.", changes_to_make: ["Add a verified result and your specific contribution."] }], provider: "Gemini" },
      privacy: "Resume file and full text are not saved.",
    } });
  });
  await page.route("**/api/v1/resumes/skill-gap/compare", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    compareCalls += 1;
    return route.fulfill({ json: { id: 992, job_title: "Frontend Developer", required_skills: ["python", "sql", "docker"], matching_skills: ["python", "sql"], missing_skills: ["docker"],
      roadmap: [{ skill: "docker", priority: "medium", topics: "Images, volumes, networking", project: "Containerize a small API", estimated_duration: "1 week" }],
      ai_guidance: null, ai_status: "complete", method: "Skill match" } });
  });
  await page.getByLabel("Resume file", { exact: true }).setInputFiles({
    name: "e2e-resume.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Alex Candidate\nEmail: alex@example.edu\nEducation: B.Tech 2027\nSkills: Python, SQL\nProject: Built a Python data analysis service."),
  });
  await page.getByRole("button", { name: "Analyze resume" }).click();
  await expect(page.getByRole("button", { name: "Analyzing…" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Back to analysis" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Resume analysis complete.");
  expect(compareCalls).toBe(0);
  await expect(page.getByRole("heading", { name: "Skills to develop (1)" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Skill gap results" })).toHaveCount(0);
  await expect(page.locator(".analysis-result").first()).toContainText("python");
  await expect(page.getByLabel("Resume file", { exact: true })).toBeHidden();
  await expect(page.getByRole("heading", { name: "Find skill gaps for a role" })).toHaveCount(0);
  await page.getByRole("button", { name: "Back to analysis" }).click();
  await expect(page.getByLabel("Resume file", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Skill Gap Matching" }).click();
  await expect(page.getByRole("heading", { name: "Analyze a resume" })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Role information (optional)", exact: true })).toHaveValue("");
  await page.getByRole("textbox", { name: "Role title", exact: true }).fill("Frontend Developer");
  await page.getByRole("button", { name: "Find skill gaps" }).click();
  await expect(page.getByRole("heading", { name: "Skills to develop (1)" })).toBeVisible();
  const viewportWidth = page.viewportSize()?.width ?? 1280;
  const toolWidth = await page.locator(".resume-tool-page").evaluate((element) => element.getBoundingClientRect().width);
  const gapGridColumns = await page.locator(".skill-gap-columns").evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length);
  expect(toolWidth).toBeGreaterThan(viewportWidth * 0.9);
  expect(gapGridColumns).toBe(1);
  expect(analyzeCalls).toBe(1);
  expect(compareCalls).toBe(1);
  await expect(page.locator(".analysis-result")).toHaveCount(1);
  await expect(page.locator(".analysis-result").last()).toContainText("docker");
  await expect(page.locator(".analysis-result").last()).not.toContainText("A student with Python and SQL skills");
  await expect(page.getByRole("button", { name: "Back to analysis" })).toBeVisible();
  await expect(page.getByLabel("Role title", { exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Back to analysis" }).click();
  await page.getByRole("button", { name: "Resume Analysis" }).click();
  await expect(page.getByLabel("Resume file", { exact: true })).toBeVisible();
  await expect(page.locator(".analysis-result")).toHaveCount(0);
  await page.reload();
  await expect(page.locator(".analysis-result")).toHaveCount(0);
  await page.getByRole("button", { name: "Skill Gap Matching" }).click();
  await expect(page.getByText("Select Resume Analysis and upload a resume before comparing it with a role.")).toBeVisible();

  await page.route("**/api/v1/chat/", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ conversation_id: 991, answer: "I can help with placement-related questions using approved campus information.",
      route: "other", queries_used: 1, daily_query_limit: 25, queries_remaining: 24, reset_date: "2026-11-26", citations: [] }),
  }));
  await page.route("**/api/v1/chat/conversations/991", (route) => route.fulfill({ status: 204 }));
  await page.goto("/chat");
  await page.getByPlaceholder("Ask about placements, approved files, company details, or notifications…").fill("What is the cafeteria menu next Tuesday?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("I can help with placement-related questions using approved campus information.")).toBeVisible();
  const savedChat = page.getByRole("button", { name: "Delete conversation: What is the cafeteria menu next Tuesday?" });
  await expect(savedChat).toBeVisible();
  await savedChat.click();
  await expect(savedChat).toHaveCount(0);
});

test("login explains API connection failures and keeps credentials out of the URL", async ({ page }) => {
  await page.route("**/api/v1/auth/login", (route) => route.abort("failed"));
  await page.goto("/login");
  await page.getByLabel("Email").fill("offline-check@example.edu");
  await page.getByLabel("Password").fill("temporary-test-value");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("form p[role=alert]")).toHaveText("CampusAI could not connect to its server. Check your connection and try again.");
  await expect(page).toHaveURL(/\/login$/);
});

test("resume review selects a section and displays its targeted edits", async ({ page }) => {
  const email = `resume-sections-${Date.now()}@example.edu`;
  let analyzeCalls = 0;
  let compareCalls = 0;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Resume Section Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.route("**/api/v1/resumes/analyze", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    analyzeCalls += 1;
    await new Promise((resolve) => setTimeout(resolve, 700));
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      id: 702, filename: "sectioned-resume.txt", skills: ["python", "fastapi"], education: ["B.E. Computer Science"],
      projects: ["Built a FastAPI inventory service."], experience: ["Software intern at Example Labs."],
      quality_feedback: [], ai_status: "complete", privacy: "Structured resume data only.",
      ai_review: { summary: "A computer science student with a software internship and API project.", strengths: ["Built a service."],
        provider: "assistant", improvement_areas: [
          { section: "Projects", current_excerpt: "Built a FastAPI inventory service.", recommendation: "The project impact is unclear.", changes_to_make: ["Add your specific contribution.", "Include a measured result if you can verify it."] },
          { section: "Experience", current_excerpt: "Software intern at Example Labs.", recommendation: "The internship details are brief.", changes_to_make: ["Describe one responsibility."] },
        ] },
    }), });
  });
  await page.route("**/api/v1/resumes/skill-gap/compare", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    compareCalls += 1;
    const uploadedResume = await route.request().postDataBuffer();
    expect(uploadedResume?.includes(Buffer.from("COMPLETE_RESUME_END_MARKER"))).toBeTruthy();
    return route.fulfill({ json: { id: 703, job_title: "Data Analyst", required_skills: ["python", "sql"],
      matching_skills: ["python"], missing_skills: ["sql"], roadmap: [], ai_guidance: null,
      ai_status: "complete", method: "AI role analysis" } });
  });
  await page.goto("/resumes");
  await page.getByLabel("Resume file", { exact: true }).setInputFiles({
    name: "sectioned-resume.txt", mimeType: "text/plain", buffer: Buffer.from("B.E. Computer Science. Built a FastAPI inventory service. Software intern at Example Labs. COMPLETE_RESUME_END_MARKER"),
  });
  await page.getByRole("button", { name: "Analyze resume" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Your resume is being extracted and reviewed with AI" })).toBeVisible();
  await expect(page.getByLabel("Resume section")).toHaveValue("Projects");
  await expect(page.getByRole("button", { name: "Back to analysis" })).toBeVisible();
  await expect(page.getByLabel("Resume file", { exact: true })).toBeHidden();
  expect(await page.locator(".analysis-result").evaluate((result) => {
    const form = result.parentElement?.querySelector("form");
    return Boolean(form && (result.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING));
  })).toBeTruthy();
  await expect(page.getByText("Add your specific contribution.")).toBeVisible();
  await page.getByLabel("Resume section").selectOption("Experience");
  await expect(page.getByText("Describe one responsibility.")).toBeVisible();
  await expect(page.locator(".selected-resume-section")).toContainText("Software intern at Example Labs.");
  const sectionWidth = await page.locator(".selected-resume-section").evaluate((element) => element.getBoundingClientRect().width);
  const analysisPanelWidth = await page.locator(".panel").first().evaluate((element) => element.getBoundingClientRect().width);
  expect(sectionWidth).toBeGreaterThan(analysisPanelWidth * 0.9);
  await expect(page.getByText("The project impact is unclear.")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Find skill gaps for a role" })).toHaveCount(0);
  await page.getByRole("button", { name: "Back to analysis" }).click();
  await expect(page.getByLabel("Resume file", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Skill Gap Matching" }).click();
  await expect(page.getByRole("heading", { name: "Analyze a resume" })).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: "Role title", exact: true })).toHaveAttribute("required", "");
  await expect(page.getByRole("textbox", { name: "Role information (optional)", exact: true })).not.toHaveAttribute("required");
  await page.getByRole("textbox", { name: "Role title", exact: true }).fill("Data Analyst");
  await page.getByRole("button", { name: "Find skill gaps" }).click();
  await expect(page.getByRole("heading", { name: "Skills to develop (1)" })).toBeVisible();
  const viewportWidth = page.viewportSize()?.width ?? 1280;
  const toolWidth = await page.locator(".resume-tool-page").evaluate((element) => element.getBoundingClientRect().width);
  const gapGridColumns = await page.locator(".skill-gap-columns").evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length);
  expect(toolWidth).toBeGreaterThan(viewportWidth * 0.9);
  expect(gapGridColumns).toBe(1);
  expect(await page.locator(".analysis-result").evaluate((result) => {
    const form = result.parentElement?.querySelector("form");
    return Boolean(form && (result.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING));
  })).toBeTruthy();
  expect(analyzeCalls).toBe(1);
  expect(compareCalls).toBe(1);
  await expect(page.locator(".analysis-result")).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "Analyze a resume" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Back to analysis" })).toBeVisible();
  await expect(page.getByLabel("Role title", { exact: true })).toBeHidden();
  await page.getByRole("button", { name: "Back to analysis" }).click();
  await page.getByRole("button", { name: "Resume Analysis" }).click();
  await expect(page.getByLabel("Resume file", { exact: true })).toBeVisible();
  await expect(page.locator(".analysis-result")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Skills to develop (1)" })).toHaveCount(0);
  await page.getByRole("button", { name: "Skill Gap Matching" }).click();
  await expect(page.getByRole("textbox", { name: "Role title", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Skills to develop (1)" })).toHaveCount(0);
});

test("resume analysis shows a clear error and exits the loading state when AI is unavailable", async ({ page }) => {
  const email = `resume-ai-error-${Date.now()}@example.edu`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Resume Error Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.route("**/api/v1/resumes/analyze", async (route) => {
    await route.fulfill({ status: 503, json: { detail: "Resume analysis is temporarily unavailable. Try again later." } });
  });
  await page.goto("/resumes");
  await page.getByLabel("Resume file", { exact: true }).setInputFiles({
    name: "resume.txt", mimeType: "text/plain", buffer: Buffer.from("Skills: Python. Project: Built an API."),
  });
  await page.getByRole("button", { name: "Analyze resume" }).click();
  await expect(page.locator(".notice-error")).toContainText("Resume analysis is temporarily unavailable");
  await expect(page.getByRole("button", { name: "Analyze resume" })).toBeEnabled();
  await expect(page.getByRole("status").filter({ hasText: "Your resume is being extracted" })).toHaveCount(0);
});

test("saved resume and skill histories restore by role and survive a failed new analysis", async ({ page }) => {
  const email = `resume-history-${Date.now()}@example.edu`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Resume History Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  const makeGap = (id: number, resumeId: number, role: string) => ({
    id, resume_analysis_id: resumeId, job_title: role, required_skills: ["Python", "SQL"],
    matching_skills: ["Python"], missing_skills: ["SQL"], roadmap: [], ai_status: "complete",
    ai_guidance: { role_summary: `${role} role`, candidate_alignment: "Python is evidenced in the saved resume.", resume_changes: [] },
    method: "Saved role comparison", created_at: `2026-11-${id === 103 ? "25" : id === 102 ? "24" : "23"}T10:00:00Z`,
  });
  const makeAnalysis = (id: number, filename: string, role: string) => ({
    id, filename, skills: ["Python"], education: ["B.Tech 2027"], projects: ["Built a Python API"], experience: [],
    quality_feedback: [], ai_status: "complete", privacy: "Resume file and full text are not saved.",
    ai_review: { summary: `Saved summary for ${role}.`, strengths: ["Built a project."], improvement_areas: [], provider: "Gemini" },
    created_at: `2026-11-${id === 3 ? "25" : "22"}T09:00:00Z`,
  });
  const analyses = [makeAnalysis(3, "resume-analyst.txt", "Data Analyst"), makeAnalysis(2, "resume-engineer.txt", "Data Engineer")];
  const gaps = [makeGap(103, 3, "Backend Developer"), makeGap(101, 3, "Data Analyst"), makeGap(102, 2, "Data Engineer")];
  await page.route("**/api/v1/resumes/history", (route) => route.fulfill({ json: analyses }));
  await page.route("**/api/v1/resumes/skill-gap/history", (route) => route.fulfill({ json: gaps }));
  await page.route("**/api/v1/resumes/history/2", (route) => route.fulfill({ status: 204, body: "" }));
  await page.route("**/api/v1/resumes/skill-gap/history/103", (route) => route.fulfill({ status: 204, body: "" }));
  await page.route("**/api/v1/resumes/history", (route) => route.request().method() === "DELETE"
    ? route.fulfill({ status: 204, body: "" })
    : route.fulfill({ json: analyses }));

  await page.route("**/api/v1/resumes/analyze", (route) => route.fulfill({ status: 503, json: {
    detail: "Gemini is temporarily overloaded or timed out. Your resume analysis was not saved. Wait briefly, then retry.",
  } }));
  await page.goto("/resumes");
  await expect(page.getByText("Saved summary for Data Analyst.")).toBeVisible();
  await page.reload();
  await expect(page.getByText("Saved summary for Data Analyst.")).toBeVisible();
  await page.getByRole("button", { name: "View saved results" }).click();
  await expect(page.getByRole("heading", { name: "Resume analyses" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Skill comparisons" })).toBeVisible();
  await expect(page.locator("#saved-resume-heading").locator("..").locator(".saved-result-card").filter({ hasText: "resume-engineer.txt" })).toBeVisible();
  await page.locator("#saved-skill-heading").locator("..").getByRole("button", { name: /Backend Developer resume-/ }).click();
  await expect(page.getByText("Saved comparison: Backend Developer")).toBeVisible();
  await page.getByRole("button", { name: "Back to saved results" }).click();
  await expect(page.getByRole("heading", { name: "Resume analyses" })).toBeVisible();
  await page.locator("#saved-skill-heading").locator("..").getByRole("button", { name: /Backend Developer resume-/ }).click();
  await expect(page.getByText("Saved comparison: Backend Developer")).toBeVisible();

  await page.getByRole("button", { name: "Back to saved results" }).click();
  await page.getByRole("button", { name: "← Back to analysis" }).click();
  await page.getByRole("button", { name: "Resume Analysis" }).click();
  await page.getByLabel("Resume file", { exact: true }).setInputFiles({
    name: "new-resume.txt", mimeType: "text/plain", buffer: Buffer.from("Skills: Java. Project: Built a Java service."),
  });
  await page.getByRole("button", { name: "Analyze resume" }).click();
  await expect(page.locator(".notice-error")).toContainText("Gemini is temporarily overloaded");
  await expect(page.getByText("resume-analyst.txt")).toBeVisible();
  await expect(page.getByRole("button", { name: "Skill gap results" })).toBeVisible();
  await page.getByRole("button", { name: "Skill gap results" }).click();
  await expect(page.getByText("Saved comparison: Backend Developer")).toBeVisible();
  await page.getByRole("button", { name: "View saved results" }).click();
  await page.getByRole("button", { name: "Delete resume analysis resume-engineer.txt" }).click();
  await expect(page.locator("#saved-resume-heading").locator("..").locator(".saved-result-card").filter({ hasText: "resume-engineer.txt" })).toHaveCount(0);
  await page.getByRole("button", { name: "Delete skill comparison Backend Developer" }).click();
  await expect(page.getByRole("button", { name: /Backend Developer/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Delete all saved results" }).click();
  await expect(page.getByText("No resume analyses saved yet.")).toBeVisible();
  await expect(page.getByText("No skill comparisons saved yet.")).toBeVisible();
});

test("student completes Hindi interview practice with localized fallback feedback", async ({ page }) => {
  const email = `hindi-practice-${Date.now()}@example.edu`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Hindi Practice Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.goto("/interviews");
  await page.getByLabel("Interview category").selectOption("technical");
  await page.getByLabel("Answer format").selectOption("typed");
  await page.getByLabel("Language").selectOption("hi");
  await page.getByLabel("Number of questions").fill("2");
  await page.getByLabel("Role or job specification (optional)").fill("Hindi E2E analyst");
  await page.getByRole("button", { name: "Start interview preparation" }).click();
  const question = page.locator(".interview-question-content > h1");
  await expect(question).toContainText(/[\u0900-\u097f]/);
  const firstQuestion = await question.innerText();

  await page.getByLabel("Your answer").fill("पहले मैंने उदाहरण से जाँचा क्योंकि परिणाम मापना जरूरी था। फिर टीम के लिए सीखा हुआ तरीका बताया।");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(question).toContainText(/[\u0900-\u097f]/);
  await expect(question).not.toHaveText(firstQuestion);
  await page.getByLabel("Your answer").fill("पहले मैंने दोनों विकल्पों की तुलना की, फिर उदाहरण से जाँचा और टीम के साथ परिणाम साझा किया।");
  await page.getByRole("button", { name: "Submit interview" }).click();
  await expect(page.getByRole("heading", { name: "Your answers and feedback" })).toBeVisible();
  await expect(page.getByText("यह पारदर्शी अभ्यास रूब्रिक है; यह भर्तीकर्ता के मूल्यांकन के बराबर नहीं है।").first()).toBeVisible();
  const historyRow = page.getByRole("row").filter({ hasText: "Hindi E2E analyst" });
  await expect(historyRow).toContainText("technical");
  await expect(historyRow).toContainText("2");
  await expect(historyRow).toContainText("completed");
  await historyRow.getByRole("button", { name: /View practice session/ }).click();
  await expect(page.getByText("पहले मैंने उदाहरण से जाँचा क्योंकि परिणाम मापना जरूरी था। फिर टीम के लिए सीखा हुआ तरीका बताया।").first()).toBeVisible();
});

test("student can ask interview questions and doubts separately", async ({ page }) => {
  const email = `interview-tutor-${Date.now()}@example.edu`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Interview Tutor Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.route("**/api/v1/interviews/ask", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ answer: { short_answer: "An index helps a database find matching rows faster.", explanation: "It narrows the rows scanned.", key_points: ["Lookups can be faster."], next_question: "What is the tradeoff of adding an index?" }, generation_mode: "assistant" }),
  }));
  await page.goto("/interviews");
  await page.getByRole("tab", { name: "Ask questions and doubts" }).click();
  await page.getByPlaceholder("Add context to tailor the answer…").fill("Backend engineer role");
  await page.getByPlaceholder("Type your interview question or doubt…").fill("What is a database index?");
  await page.getByRole("button", { name: "Ask question" }).click();
  await expect(page.locator(".interview-qa-question")).toContainText("What is a database index?");
  await expect(page.locator(".interview-qa-answer")).toContainText("Answer");
  await expect(page.getByText("An index helps a database find matching rows faster.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Explanation" })).toBeVisible();
});

test("student can select and submit a multiple-choice interview answer", async ({ page }) => {
  const email = `interview-mcq-${Date.now()}@example.edu`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Multiple Choice Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.route("**/api/v1/interviews/history", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([
    { id: 951, category: "technical", language: "en", focus: "Backend developer", question_type: "multiple_choice", status: "completed", response_count: 1, question_limit: 1, average_score: 5, created_at: "2026-11-22T00:00:00Z" },
  ]) }));
  await page.route("**/api/v1/interviews/history/951", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    id: 951, category: "technical", language: "en", focus: "Backend developer", question_type: "multiple_choice", status: "completed", average_score: 5, answered_count: 1,
    results: [{ question: "Which method reads an HTTP resource?", answer: "B. GET", score: 5, feedback: { options: [{ id: "A", text: "POST" }, { id: "B", text: "GET" }, { id: "C", text: "PATCH" }, { id: "D", text: "DELETE" }], correct_option: "B", correct_text: "GET", selected_option: "B", strengths: ["Correct choice."], improvements: ["Correct answer: B. GET"] } }],
  }) }));

  await page.route("**/api/v1/interviews/sessions", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
      id: 951, category: "technical", language: "en", question: "Which method reads an HTTP resource?",
      question_type: "multiple_choice", options: [{ id: "A", text: "POST" }, { id: "B", text: "GET" }, { id: "C", text: "PATCH" }, { id: "D", text: "DELETE" }],
      focus: "Backend developer", generation_mode: "assistant", language_note: null, question_limit: 1,
    }) });
  });
  await page.route("**/api/v1/interviews/sessions/951/responses", (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ id: 951, status: "completed", completed: true, answered_count: 1, question_limit: 1, question_type: "multiple_choice", correct_count: 1, average_score: 1,
      results: [{ question: "Which method reads an HTTP resource?", answer: "B. GET", score: 1,
        feedback: { strengths: ["Correct choice."], improvements: ["Correct answer: B. GET"], assessment_note: "Practice only." } }] }),
  }));
  await page.goto("/interviews");
  await page.getByLabel("Interview category").selectOption("technical");
  await page.getByLabel("Answer format").selectOption("multiple_choice");
  await page.getByRole("button", { name: "Start interview preparation" }).click();
  await expect(page.getByText("Which method reads an HTTP resource?")).toBeVisible();
  await page.getByLabel(/B\. GET/).check();
  await page.getByRole("button", { name: "Submit interview" }).click();
  await expect(page.getByRole("heading", { name: "Your answers and feedback" })).toBeVisible();
  await expect(page.getByText("1/1", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Correct answers", { exact: true })).toBeVisible();
  await expect(page.getByText("Correct answer: B. GET").first()).toBeVisible();
  await page.getByRole("row").filter({ hasText: "Backend developer" }).getByRole("button", { name: "View practice session 951" }).click();
  await expect(page.getByText("B. GET — Correct answer — Your choice")).toBeVisible();
});

test("multiple-choice options update when the next interview question loads", async ({ page }) => {
  const email = `changing-options-${Date.now()}@example.edu`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Options Student");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.route("**/api/v1/interviews/sessions", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
      id: 952, category: "technical", language: "en", question: "Which data structure maps keys to values?",
      question_type: "multiple_choice", options: [{ id: "A", text: "Hash map" }, { id: "B", text: "Queue" }, { id: "C", text: "Stack" }, { id: "D", text: "Tree" }],
      focus: null, generation_mode: "assistant", language_note: null, question_limit: 2,
    }) });
  });
  await page.route("**/api/v1/interviews/sessions/952/responses", async (route) => {
    const request = route.request().postDataJSON();
    if (request.question === "Which data structure maps keys to values?") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ completed: false, answered_count: 1, question_limit: 2,
        question: "Which database feature speeds up lookups?", question_type: "multiple_choice", generation_mode: "assistant",
        options: [{ id: "A", text: "Index" }, { id: "B", text: "Trigger" }, { id: "C", text: "View" }, { id: "D", text: "Transaction" }] }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: 952, status: "completed", completed: true, answered_count: 2,
      question_limit: 2, average_score: 4, results: [] }) });
  });
  await page.goto("/interviews");
  await page.getByLabel("Interview category").selectOption("technical");
  await page.getByLabel("Answer format").selectOption("multiple_choice");
  await page.getByLabel("Number of questions").fill("2");
  await page.getByRole("button", { name: "Start interview preparation" }).click();
  await expect(page.getByRole("heading", { name: "Which data structure maps keys to values?" })).toBeVisible();
  await expect(page.getByLabel("A. Hash map")).toBeVisible();
  await page.getByLabel("A. Hash map").check();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Which database feature speeds up lookups?" })).toBeVisible();
  await expect(page.getByLabel("A. Index")).toBeVisible();
  await expect(page.getByLabel("A. Hash map")).toHaveCount(0);
  await page.getByLabel("A. Index").check();
  await page.getByRole("button", { name: "Submit interview" }).click();
  await expect(page.getByRole("heading", { name: "Your answers and feedback" })).toBeVisible();
});

test("placement administrator signs in and manages verified company records", async ({ page }) => {
  test.setTimeout(60_000);
  const companyName = `E2E Verified Company ${Date.now()}`;
  e2eCompanyName = companyName;
  await page.goto("/login");
  await page.getByLabel("Email").fill(process.env.E2E_STAFF_EMAIL ?? "");
  await page.getByLabel("Password").fill(process.env.E2E_STAFF_PASSWORD ?? "");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/admin$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();

  await page.reload();
  await expect(page).toHaveURL(/\/admin$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  await page.getByRole("link", { name: "Access control" }).click();
  await expect(page).toHaveURL(/\/admin\/access-control$/);
  await expect(page.getByRole("heading", { name: /User management/ })).toBeVisible();
  await expect(page.getByText("placement-admin-e2e@example.edu")).toBeVisible();
  await page.getByRole("link", { name: "Back to admin dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  await page.getByRole("link", { name: "Audit", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/audit$/);
  await expect(page.getByRole("heading", { name: "Recent admin activity" })).toBeVisible();
  await page.getByRole("link", { name: "Back to admin dashboard" }).click();
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();

  const documentTitle = `E2E Placement Policy ${Date.now()}`;
  await page.locator('input[type="file"]').setInputFiles({
    name: `${documentTitle}.txt`,
    mimeType: "text/plain",
    buffer: Buffer.from("The placement office requires applicants to complete the profile before applying for a placement drive."),
  });
  const uploadResponsePromise = page.waitForResponse((response) => response.url().endsWith("/api/v1/documents/upload") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Upload for review" }).click();
  const uploadedDocument = await (await uploadResponsePromise).json() as { id: number };
  const documentRow = page.getByRole("row").filter({ hasText: documentTitle });
  await expect(documentRow).toContainText("pending");
  await documentRow.getByRole("button", { name: "Approve" }).click();
  await expect(documentRow).toContainText("approved");

  await page.getByLabel("Name", { exact: true }).fill(companyName);
  await page.getByLabel("Industry", { exact: true }).fill("Software");
  await page.getByLabel("Role", { exact: true }).first().fill("Software Engineer");
  await page.getByLabel("Minimum CGPA").fill("7.5");
  await page.getByLabel("Eligible branches (comma separated)").fill("Computer Science");
  await page.getByLabel("Maximum active backlogs").fill("0");
  await page.getByLabel("Approved source document").selectOption(String(uploadedDocument.id));
  const companyResponsePromise = page.waitForResponse((response) => response.url().endsWith("/api/v1/companies/") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Save company" }).click();
  const company = await (await companyResponsePromise).json() as { id: number };
  await expect(page.locator("strong").filter({ hasText: companyName })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Company information saved" })).toBeVisible();

  await page.getByRole("combobox", { name: "Company" }).selectOption(String(company.id));
  await page.getByLabel("Drive title").fill("Graduate Software Engineer Drive");
  await page.getByLabel("Role", { exact: true }).nth(1).fill("Software Engineer");
  await page.getByRole("button", { name: "Publish drive" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Placement drive published" })).toBeVisible();

});

test("student attaches a resume to each application without resume analysis gating eligibility", async ({ page }) => {
  expect(e2eCompanyName).not.toBe("");
  const email = `eligible-${Date.now()}@example.edu`;
  const password = "e2e-safe-password-2026";
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Eligible Candidate");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  // Academic details are managed by placement staff, so update the test student
  // through the same administrator API instead of expecting a student edit form.
  const apiBase = process.env.E2E_API_BASE_URL ?? "http://localhost:8100";
  const adminLogin = await page.request.post(`${apiBase}/api/v1/auth/login`, {
    data: { email: process.env.E2E_STAFF_EMAIL, password: process.env.E2E_STAFF_PASSWORD },
  });
  expect(adminLogin.ok()).toBeTruthy();
  const { access_token: adminToken } = await adminLogin.json() as { access_token: string };
  const recordsResponse = await page.request.get(`${apiBase}/api/v1/admin/students`, {
    headers: { Authorization: `Bearer ${adminToken}` },
  });
  expect(recordsResponse.ok()).toBeTruthy();
  const students = await recordsResponse.json() as Array<{ id: number; email: string }>;
  const student = students.find((record) => record.email === email);
  expect(student).toBeDefined();
  const updateResponse = await page.request.put(`${apiBase}/api/v1/admin/students/${student!.id}`, {
    headers: { Authorization: `Bearer ${adminToken}` },
    data: { branch: "Computer Science", graduation_year: 2027, cgpa: 8.5, active_backlogs: 0 },
  });
  expect(updateResponse.ok()).toBeTruthy();

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.goto("/companies");
  const companyCard = page.locator(".company-card").filter({ hasText: e2eCompanyName });
  await companyCard.getByRole("button", { name: "Check my eligibility" }).click();
  await expect(companyCard.locator(".eligibility-result")).toContainText("eligible");
  const driveRow = page.getByRole("row").filter({ hasText: e2eCompanyName });
  await expect(driveRow.getByRole("button", { name: "Apply" })).toBeDisabled();
  await driveRow.getByLabel(/Resume for/).setInputFiles({ name: "candidate.txt", mimeType: "text/plain", buffer: Buffer.from("Candidate skills: Python") });
  await expect(driveRow.getByRole("button", { name: "Apply" })).toBeEnabled();
  const applicationResponse = page.waitForResponse((response) => response.url().includes("/api/v1/placement-drives/") && response.url().endsWith("/apply") && response.request().method() === "POST");
  await driveRow.getByRole("button", { name: "Apply" }).click();
  expect((await applicationResponse).status()).toBe(201);
  await expect(driveRow.getByText("Applied", { exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Applied to");
  await page.goto("/dashboard");
  const activity = page.locator(".panel").filter({ has: page.getByRole("heading", { name: "Applications" }) });
  await expect(activity).toContainText(e2eCompanyName);
  await expect(activity).toContainText("applied");
});

test("chat shows a clean answer without revealing source details", async ({ page }) => {
  await page.route("**/api/v1/chat/", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        conversation_id: 9876,
        answer: "The minimum CGPA is 7.5.",
        route: "faq",
        queries_used: 1,
        daily_query_limit: 25,
        queries_remaining: 24,
        reset_date: "2026-11-26",
        citations: [{ citation: 1, document_id: 88, title: "Approved Placement Policy", version: 2, page: 3,
          section: "Eligibility", effective_date: null, status: "approved" }],
        abstained: false,
      }),
    });
  });

  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Cited Chat Student");
  await page.getByLabel("Email").fill(`cited-chat-${Date.now()}@example.edu`);
  await page.getByLabel("Password").fill("e2e-safe-password-2026");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  await page.goto("/chat");
  await page.getByPlaceholder("Ask about placements, approved files, company details, or notifications…").fill("What CGPA is required?");
  await page.getByRole("button", { name: "Send" }).click();
  const answer = page.locator(".message-assistant");
  await expect(answer).toContainText("The minimum CGPA is 7.5.");
  await expect(answer).not.toContainText("Approved Placement Policy");
  await expect(answer).not.toContainText("[1]");
});


