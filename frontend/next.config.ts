import type { NextConfig } from "next";

// On Vercel, VERCEL=1 is always set. Fail loud there if the backend URL is
// missing rather than silently falling back to localhost (which 404s on every
// API call). Local builds skip this check so `next build` works without env.
if (process.env.VERCEL === "1" && !process.env.NEXT_PUBLIC_API_BASE_URL) {
  throw new Error(
    "NEXT_PUBLIC_API_BASE_URL is not set. Add it to your Vercel environment variables before deploying."
  );
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
