import type { Metadata } from "next";
import { AppShell } from "./shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "CampusAI | Placement Intelligence",
  description: "AI-powered college placement intelligence platform",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><AppShell>{children}</AppShell></body></html>;
}
