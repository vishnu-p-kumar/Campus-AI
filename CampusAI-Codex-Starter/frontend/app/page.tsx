import Link from "next/link";
import { ApiHealth } from "./components/api-health";

const features = [
  ["Policy answers with sources", "Ask about placement rules and review the approved document and page behind each answer."],
  ["Explainable eligibility", "Compare a saved academic profile with source-linked company rules. Unclear criteria require staff review."],
  ["Resume and skill planning", "Extract common resume sections and map supported skills to a role description."],
  ["Practice workflows", "Work through interview prompts and receive structured, clearly labelled practice feedback."],
];

export default function Home() {
  return <>
    <section className="hero">
      <div><p className="eyebrow">PLACEMENT INTELLIGENCE FOR STUDENTS</p><h1>Make your next career move with evidence.</h1><p className="hero-copy">CampusAI brings placement documents, eligibility checks, application tracking and career preparation into one student workspace.</p>
        <div className="hero-actions"><Link className="button button-primary" href="/register">Create student account</Link><Link className="button button-secondary" href="/login">Sign in</Link></div>
        <ApiHealth />
      </div>
      <aside className="hero-panel"><p className="eyebrow">BUILT FOR TRUST</p><strong>Clear evidence for high stakes questions</strong><ul><li>Placement policy answers cite approved documents</li><li>Eligibility checks use deterministic rules</li><li>Missing policy evidence is sent for review</li><li>Resume suggestions do not promise an ATS score</li></ul></aside>
    </section>
    <section><p className="eyebrow">ONE WORKSPACE</p><h2>Tools for the full placement journey</h2><div className="feature-grid">{features.map(([title, description]) => <article className="feature-card" key={title}><strong>{title}</strong><p>{description}</p></article>)}</div></section>
    <footer className="home-footer"><span>CampusAI · Research-oriented placement intelligence</span><div><Link href="/about">About</Link><Link href="/privacy">Privacy</Link><Link href="/contact">Contact</Link></div></footer>
  </>;
}
