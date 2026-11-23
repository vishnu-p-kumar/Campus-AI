"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "../lib/api";

export default function ResetPasswordPage() {
  const { api } = useAuth();
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [delivery, setDelivery] = useState<boolean | null>(null);
  useEffect(() => { const query = new URLSearchParams(window.location.search); setEmail(query.get("email") ?? ""); setToken(query.get("token") ?? ""); }, []);
  async function request(event: FormEvent) {
    event.preventDefault(); setError(""); setMessage("");
    try { const result = await api<{ message: string; email_delivery_configured: boolean }>("/api/v1/auth/password-reset/request", { method: "POST", body: JSON.stringify({ email }) }); setMessage(result.message); setDelivery(result.email_delivery_configured); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not request password reset"); }
  }
  async function complete(event: FormEvent) {
    event.preventDefault(); setError(""); setMessage("");
    try { const result = await api<{ message: string }>("/api/v1/auth/password-reset/complete", { method: "POST", body: JSON.stringify({ email, token, new_password: password }) }); setMessage(result.message); setToken(""); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not reset password"); }
  }
  return <div className="center-page"><section className="panel auth-card"><p className="eyebrow">ACCOUNT RECOVERY</p><h1>Reset password</h1><p className="muted">Reset links are single-use and expire after 30 minutes.</p>{error && <div className="notice notice-error">{error}</div>}{message && <div className="notice notice-info">{message}{delivery === false && <p>Email delivery is not configured on this server. Set SMTP_HOST and SMTP_FROM_EMAIL in the backend environment.</p>}</div>}{token ? <form className="form-stack" onSubmit={complete}><label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label><label>New password<input type="password" minLength={6} maxLength={128} required value={password} onChange={(e) => setPassword(e.target.value)} /><small>At least 6 characters.</small></label><button className="button button-primary">Set new password</button></form> : <form className="form-stack" onSubmit={request}><label>Account email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label><button className="button button-primary">Request reset link</button></form>}<p className="muted"><Link href="/login">Return to sign in</Link></p></section></div>;
}
