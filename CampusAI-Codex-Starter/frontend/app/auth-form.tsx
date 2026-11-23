"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useAuth } from "./lib/api";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { login, register: createAccount } = useAuth();
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const schema = useMemo(() => z.object({
    full_name: z.string().optional(),
    email: z.string().email("Enter a valid email address"),
    password: z.string().min(mode === "register" ? 6 : 1, mode === "register" ? "Use at least 6 characters" : "Enter your password").max(128),
  }).refine((value) => mode !== "register" || (value.full_name?.trim().length ?? 0) >= 2, { path: ["full_name"], message: "Enter your full name" }), [mode]);
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema), defaultValues: { full_name: "", email: "", password: "" } });
  async function submit(values: z.infer<typeof schema>) {
    setError(""); setBusy(true);
    try {
      const account = mode === "register" ? await createAccount(values.full_name?.trim() ?? "", values.email, values.password) : await login(values.email, values.password);
      router.push(account.role === "student" ? "/dashboard" : "/admin");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Request failed"); }
    finally { setBusy(false); }
  }
  return <section className="auth-card panel">
    <p className="eyebrow">STUDENT ACCESS</p>
    <h1>{mode === "login" ? "Welcome back" : "Create your student account"}</h1>
    <p className="muted">Sign in with your CampusAI account email. Students should use their college email; administrator accounts are created by the system administrator.</p>
    <form className="form-stack" method="post" onSubmit={form.handleSubmit(submit)}>
      {mode === "register" && <label>Full name<input maxLength={160} autoComplete="name" {...form.register("full_name")} />{form.formState.errors.full_name && <small className="field-error">{form.formState.errors.full_name.message}</small>}</label>}
      <label>Email<input type="email" autoComplete="email" {...form.register("email")} />{form.formState.errors.email && <small className="field-error">{form.formState.errors.email.message}</small>}</label>
      <label>Password<input type="password" minLength={mode === "register" ? 6 : undefined} maxLength={128} autoComplete={mode === "login" ? "current-password" : "new-password"} {...form.register("password")} />{mode === "register" && <small>At least 6 characters.</small>}{form.formState.errors.password && <small className="field-error">{form.formState.errors.password.message}</small>}</label>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      <button className="button button-primary auth-submit" style={{ color: "#fff" }} type="submit" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</button>
    </form>
    <p className="muted">{mode === "login" ? <><Link href="/reset-password">Forgot password?</Link> · New student? <Link href="/register">Create an account</Link></> : <>Already registered? <Link href="/login">Sign in</Link></>}</p>
  </section>;
}
