"use client";

import { FormEvent, useState } from "react";

export default function ContactPage() {
  const [draft, setDraft] = useState({ name: "", email: "", message: "" });
  const [prepared, setPrepared] = useState("");
  const [copied, setCopied] = useState(false);
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setPrepared(`From: ${draft.name} <${draft.email}>\n\n${draft.message}`); }
  async function copy() { await navigator.clipboard.writeText(prepared); setCopied(true); }
  return <section className="panel" style={{ maxWidth: 680, margin: "0 auto" }}><p className="eyebrow">CONTACT</p><h1>Contact the Placement Office</h1><p className="muted">This local starter does not send email. Prepare your message here, then copy it into your institution&apos;s published contact channel.</p><form className="form-stack" onSubmit={submit}><label>Your name<input required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label><label>Email<input type="email" required value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} /></label><label>Message<textarea rows={5} minLength={10} required value={draft.message} onChange={(e) => setDraft({ ...draft, message: e.target.value })} /></label><button className="button button-primary">Prepare message</button></form>{prepared && <div className="analysis-result"><label>Prepared message<textarea readOnly rows={5} value={prepared} /></label><button type="button" className="button button-secondary" onClick={copy}>{copied ? "Copied" : "Copy message"}</button><p className="muted small-note">No information was sent or stored.</p></div>}</section>;
}
