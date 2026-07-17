/** @type {import('next').NextConfig} */
const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig = {
  // Same-origin API: the browser only ever talks to the frontend origin;
  // Next proxies /api/* to the backend (no CORS surface, PD-V3-08/T1).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
