/* eslint-disable @typescript-eslint/no-require-imports */
const { spawn, spawnSync } = require("node:child_process");
const { setTimeout: delay } = require("node:timers/promises");
const net = require("node:net");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const { randomUUID } = require("node:crypto");

const frontend = path.resolve(__dirname, "..");
const repository = path.resolve(frontend, "..");
const databaseDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "campusai-e2e-"));
const databaseFile = path.join(databaseDirectory, "campusai.db");
const databaseUrl = `sqlite:///${databaseFile.replace(/\\/g, "/")}`;
const uploadDirectory = path.resolve(repository, `.e2e-uploads-${randomUUID()}`);
const nextOutputDirectory = path.join(frontend, `.next-e2e-${randomUUID()}`);
const temporaryTsconfig = path.join(frontend, `tsconfig.e2e-${randomUUID()}.json`);
const children = [];

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
}

async function ensurePortFree(port) {
  await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => server.close(resolve));
  }).catch(() => { throw new Error(`Port ${port} is already in use; stop that process before running E2E tests.`); });
}

async function availablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

function start(command, args, cwd, env) {
  const child = spawn(command, args, {
    cwd,
    env: { ...process.env, ...env },
    stdio: ["ignore", "inherit", "inherit"],
    windowsHide: true,
    detached: process.platform !== "win32",
  });
  child.once("error", (error) => fail(`Could not start ${command}: ${error.message}`));
  children.push(child);
  return child;
}

async function waitFor(url, child, label) {
  const deadline = Date.now() + 120_000;
  let lastError;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`${label} exited before becoming ready (code ${child.exitCode}).`);
    try {
      const response = await fetch(url);
      if (response.ok) return;
      lastError = new Error(`${label} returned HTTP ${response.status}`);
    } catch (error) { lastError = error; }
    await delay(500);
  }
  throw new Error(`${label} did not become ready: ${lastError?.message ?? "timeout"}`);
}

function stop(child) {
  const hasExited = () => child && (child.exitCode !== null || child.signalCode !== null);
  if (!child || hasExited()) return Promise.resolve(true);
  let terminationRequested = false;
  if (process.platform === "win32") {
    try { terminationRequested = child.kill("SIGTERM"); } catch { /* Process exited during shutdown. */ }
  } else {
    try {
      process.kill(-child.pid, "SIGTERM");
      terminationRequested = true;
    } catch { /* Process exited during shutdown. */ }
  }
  return new Promise((resolve) => {
    let finished = false;
    const complete = (stopped) => {
      if (finished) return;
      finished = true;
      clearTimeout(timeout);
      child.off("exit", onExit);
      resolve(stopped);
    };
    const onExit = () => complete(true);
    const timeout = setTimeout(() => {
      if (!hasExited() && !terminationRequested) {
        process.stderr.write(`Could not confirm shutdown for test server PID ${child.pid} (exit ${child.exitCode}, signal ${child.signalCode}).\n`);
      }
      complete(hasExited() || terminationRequested);
    }, 5_000);
    child.once("exit", onExit);
    if (hasExited()) complete(true);
  });
}

async function main() {
  await ensurePortFree(8100);
  const webPort = await availablePort();
  // Keep frontend and API on the same loopback hostname. Mixing localhost and
  // 127.0.0.1 makes the development refresh cookie cross-site (SameSite=Lax).
  const webUrl = `http://127.0.0.1:${webPort}`;
  if (!uploadDirectory.startsWith(`${repository}${path.sep}`)) throw new Error("Refusing to clean uploads outside the project E2E directory.");
  if (!temporaryTsconfig.startsWith(`${frontend}${path.sep}`)) throw new Error("Refusing to create E2E TypeScript settings outside the frontend directory.");
  const tsconfigSource = fs.readFileSync(path.join(frontend, "tsconfig.json"), "utf8").replace(/^\uFEFF/, "");
  const tsconfig = JSON.parse(tsconfigSource);
  tsconfig.include = [...new Set([...(tsconfig.include ?? []), `${path.basename(nextOutputDirectory)}/types/**/*.ts`])];
  fs.writeFileSync(temporaryTsconfig, JSON.stringify(tsconfig, null, 2));
  const env = {
    DATABASE_URL: databaseUrl,
    UPLOAD_DIRECTORY: uploadDirectory,
    CORS_ORIGINS: webUrl,
    GEMINI_API_KEY: "",
    GEMINI_CHAT_API_KEY: "",
    QDRANT_URL: "",
    QDRANT_API_KEY: "",
    // Browser workflows make many legitimate refresh calls in one isolated run;
    // rate limiting itself is covered by backend unit and PostgreSQL tests.
    AUTH_RATE_LIMIT_PER_MINUTE: "1000",
  };
  const migration = spawnSync("python", ["-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"], {
    cwd: repository,
    env: { ...process.env, ...env },
    stdio: "inherit",
    windowsHide: true,
  });
  if (migration.error || migration.status !== 0) throw migration.error ?? new Error("E2E database migration failed.");
  const staffEmail = "placement-admin-e2e@example.edu";
  const staffPassword = "e2e-administrator-password-2026";
  const createStaff = spawnSync("python", ["-c", "import sys; sys.path.insert(0, 'backend'); from sqlalchemy import select; from app.db import SessionLocal; from app.models import User; from app.security import hash_password; db=SessionLocal(); email='placement-admin-e2e@example.edu'; user=db.scalar(select(User).where(User.email == email)); db.add(User(email=email, full_name='E2E Placement Administrator', password_hash=hash_password('e2e-administrator-password-2026'), role='administrator') if user is None else user); db.commit(); db.close()"], {
    cwd: repository,
    env: { ...process.env, ...env },
    stdio: "inherit",
    windowsHide: true,
  });
  if (createStaff.error || createStaff.status !== 0) throw createStaff.error ?? new Error("Could not provision the isolated E2E administrator.");

  const api = start("python", ["-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8100"], repository, env);
  const next = start(process.execPath, [path.join(frontend, "node_modules/next/dist/bin/next"), "dev", "--hostname", "127.0.0.1", "--port", String(webPort)], frontend, {
    ...env,
    NEXT_DIST_DIR: path.basename(nextOutputDirectory),
    NEXT_TSCONFIG_PATH: path.basename(temporaryTsconfig),
    NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8100",
  });
  await Promise.all([waitFor("http://localhost:8100/health/ready", api, "API"), waitFor(webUrl, next, "Next.js")]);

  const tests = spawnSync(process.execPath, [path.join(frontend, "node_modules/@playwright/test/cli.js"), "test", ...process.argv.slice(2)], {
    cwd: frontend,
    env: { ...process.env, E2E_WEB_URL: webUrl, E2E_API_BASE_URL: "http://127.0.0.1:8100", E2E_STAFF_EMAIL: staffEmail, E2E_STAFF_PASSWORD: staffPassword },
    stdio: "inherit",
    windowsHide: true,
  });
  if (tests.error || tests.status !== 0) process.exitCode = tests.status || 1;
}

main()
  .catch((error) => fail(error.message || String(error)))
  .finally(async () => {
    const stopped = await Promise.all([...children].reverse().map(stop));
    if (stopped.every(Boolean)) {
      fs.rmSync(uploadDirectory, { recursive: true, force: true, maxRetries: 5, retryDelay: 250 });
      fs.rmSync(databaseDirectory, { recursive: true, force: true, maxRetries: 5, retryDelay: 250 });
      if (!nextOutputDirectory.startsWith(`${frontend}${path.sep}`)) throw new Error("Refusing to clean E2E build data outside the frontend directory.");
      fs.rmSync(nextOutputDirectory, { recursive: true, force: true, maxRetries: 5, retryDelay: 250 });
      fs.rmSync(temporaryTsconfig, { force: true });
    } else {
      process.stderr.write(`A test server did not exit cleanly; retained its isolated data at ${databaseDirectory} and ${uploadDirectory}.\n`);
      process.exitCode = 1;
    }
    process.exit(process.exitCode ?? 0);
  });
