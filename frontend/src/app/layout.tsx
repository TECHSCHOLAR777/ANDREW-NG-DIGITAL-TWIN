import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Andrew Ng Digital Twin - RAG Learning Companion",
  description: "An interactive RAG dialogue twin of Dr. Andrew Ng, featuring vector-anchored knowledge graph memory states and pedagogical machine learning instructions.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
