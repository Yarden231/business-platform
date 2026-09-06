import type { NextConfig } from 'next';

/**
 * The browser only ever talks to the web origin. Everything under `/api/v1` is
 * rewritten server-side to the API service, which keeps the session cookie
 * first-party and lets `SameSite=Lax` do its job (ADR-0005).
 *
 * In production the same shape is produced by path-based routing at the
 * ingress, so no application code has to know the API's address either way.
 */
const apiInternalUrl = process.env.API_INTERNAL_URL ?? 'http://localhost:8000';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${apiInternalUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
