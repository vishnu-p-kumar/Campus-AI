/* eslint-disable @typescript-eslint/no-require-imports */
const { chromium } = require("@playwright/test");
const { randomBytes, randomUUID } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const localEnv = fs.existsSync(path.join(__dirname, "..", ".env.local"))
  ? fs.readFileSync(path.join(__dirname, "..", ".env.local"), "utf8").replace(/^\uFEFF/, "")
  : "";
const configuredApi = localEnv.match(/^NEXT_PUBLIC_API_BASE_URL=(.+)$/m)?.[1]?.trim();
const webUrl = process.env.CAMPUSAI_LOCAL_WEB_URL || "http://127.0.0.1:3101";
const apiBase = process.env.CAMPUSAI_LOCAL_API_URL || configuredApi || "http://127.0.0.1:8000";

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const email = `local-login-smoke-${randomUUID()}@example.edu`;
  const password = randomBytes(24).toString("base64url");
  let cleanupToken;
  let registrationAttempted = false;
  let cleanupComplete = false;
  try {
    const pageResponse = await page.goto(`${webUrl}/login`, { waitUntil: "networkidle" });
    if (!pageResponse?.ok()) throw new Error(`Frontend returned HTTP ${pageResponse?.status() ?? "no response"}.`);

    registrationAttempted = true;
    const registered = await page.evaluate(async ({ api, accountEmail, accountPassword }) => {
      const response = await fetch(`${api}/api/v1/auth/register`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: accountEmail, full_name: "Local Login Smoke Check", password: accountPassword }),
      });
      return { status: response.status, body: response.ok ? await response.json() : null };
    }, { api: apiBase, accountEmail: email, accountPassword: password });
    if (registered.status !== 201 || !registered.body?.access_token) {
      throw new Error(`Browser registration request returned HTTP ${registered.status}.`);
    }
    cleanupToken = registered.body.access_token;

    await page.goto(`${webUrl}/login`, { waitUntil: "networkidle" });
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL(/\/dashboard$/, { timeout: 10_000 });
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForURL(/\/dashboard$/, { timeout: 10_000 });

    const deleted = await deleteSmokeAccount(cleanupToken);
    cleanupToken = undefined;
    if (deleted !== 204) throw new Error(`Temporary account cleanup returned HTTP ${deleted}.`);
    cleanupComplete = true;
    process.stdout.write("LOCAL_BROWSER_REGISTER=passed\nLOCAL_BROWSER_LOGIN=passed\nLOCAL_SESSION_REFRESH=passed\nTEMP_ACCOUNT_CLEANUP=passed\n");
  } finally {
    if (!cleanupComplete) {
      const deleted = cleanupToken
        ? await deleteSmokeAccount(cleanupToken).catch(() => 0)
        : registrationAttempted ? await deleteSmokeAccountByLogin(email, password).catch(() => 0) : 204;
      if (deleted !== 204) process.stderr.write("Temporary account cleanup was not confirmed.\n");
    }
    await browser.close();
  }
}

async function deleteSmokeAccount(token) {
  const response = await fetch(`${apiBase}/api/v1/students/me`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  return response.status;
}

async function deleteSmokeAccountByLogin(email, password) {
  const response = await fetch(`${apiBase}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (response.status === 401) return 204;
  if (!response.ok) return response.status;
  const body = await response.json();
  return deleteSmokeAccount(body.access_token);
}

main().catch((error) => {
  process.stderr.write(`Local browser login check failed (${error?.name || "unknown error"}).\n`);
  process.exitCode = 1;
});
