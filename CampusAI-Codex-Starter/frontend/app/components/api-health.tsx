"use client";

import { useEffect, useState } from "react";

type HealthState = "checking" | "online" | "offline";

const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export function ApiHealth() {
  const [state, setState] = useState<HealthState>("checking");

  useEffect(() => {
    const controller = new AbortController();

    fetch(`${apiBaseUrl}/health`, { signal: controller.signal, cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("Health request failed");
        return response.json() as Promise<{ status?: string }>;
      })
      .then((health) => setState(health.status === "ok" ? "online" : "offline"))
      .catch(() => {
        if (!controller.signal.aborted) setState("offline");
      });

    return () => controller.abort();
  }, []);

  const message = {
    checking: "Checking API connection…",
    online: "Backend API connected",
    offline: "Backend API unavailable. Start the FastAPI server to connect.",
  }[state];

  return (
    <div className={`api-status api-status-${state}`} role="status" aria-live="polite">
      <span className="api-status-dot" aria-hidden="true" />
      {message}
    </div>
  );
}
