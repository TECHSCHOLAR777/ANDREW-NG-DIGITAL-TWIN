import type { Metadata } from "next";
import "./globals.css";
import { Poppins, Source_Sans_3 } from "next/font/google";
import { cn } from "@/lib/utils";
import { ThemeProvider, themeInitScript } from "@/components/theme-provider";

/**
 * Typography follows the two sites this project's audience already reads.
 *
 * Measured rather than assumed, by reading computed styles on each site:
 *   deeplearning.ai  headings set in Poppins
 *   coursera.org     body set in Source Sans Pro, 642 elements
 *
 * Source Sans 3 is the maintained continuation of Source Sans Pro, same
 * design, still on Google Fonts. Poppins is geometric and a little wide, which
 * reads well large and poorly small, so it is reserved for headings.
 *
 * Weights are listed explicitly. Requesting the whole family ships far more
 * than a UI uses.
 */
const heading = Poppins({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-poppins",
  display: "swap",
});

const sans = Source_Sans_3({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-source",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Andrew Ng Digital Twin",
  description:
    "Converse with a grounded, unofficial AI recreation of Andrew Ng's public knowledge, reasoning, and voice — with contextual memory across sessions. An academic project, not affiliated with or endorsed by Andrew Ng.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      // The theme script mutates data-theme before React hydrates; without
      // this, React warns about the server/client attribute mismatch.
      suppressHydrationWarning
      className={cn(
        "h-full antialiased",
        "font-sans",
        sans.variable,
        heading.variable
      )}
    >
      <head>
        {/* Runs before first paint so there is no flash of the wrong theme. */}
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="min-h-full flex flex-col">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
