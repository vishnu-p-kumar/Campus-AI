"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { AuthProvider, useAuth } from "./lib/api";

const links = [
  ["/dashboard", "Overview"], ["/companies", "Companies & drives"], ["/chat", "Placement assistant"],
  ["/resumes", "Resume & skills"], ["/interviews", "Interview practice"], ["/notifications", "Notifications"],
];

function Navigation() {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  return <header className="topbar">
    <Link className="brand" href="/">Campus<span>AI</span></Link>
    <nav aria-label="Main navigation" className="nav-links">
      {links.map(([href, label]) => <Link key={href} className={pathname === href ? "nav-active" : ""} href={href}>{label}</Link>)}
      {user && ["administrator", "placement_officer"].includes(user.role) && <Link className={pathname === "/admin" ? "nav-active" : ""} href="/admin">Admin</Link>}
    </nav>
    <div className="account-area">
      {!user && !loading && <><Link href="/login">Sign in</Link><Link className="button button-primary button-small" href="/register" style={{ color: "#fff" }}>Create account</Link></>}
    </div>
  </header>;
}

function AccountMenu() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  if (loading) return null;
  return <details className="account-menu"><summary aria-label="Open account menu">{user ? user.role === "administrator" ? "A" : user.full_name.trim().charAt(0).toUpperCase() : "C"}</summary><div className="account-menu-panel">{user?.role === "student" && <Link href="/student-details">Student details</Link>}{user ? <button type="button" onClick={async () => { await logout(); router.push("/"); }}>Log out</button> : <Link href="/login">Sign in</Link>}</div></details>;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return <AuthProvider><Navigation /><main className="page-content">{children}</main><AccountMenu /></AuthProvider>;
}
