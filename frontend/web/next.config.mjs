const API = process.env.UEOS_API_URL || "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
export default {
  reactStrictMode: true,
  // Same-origin proxy to the FastAPI backend: no CORS, tokens never leave our origin.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};
