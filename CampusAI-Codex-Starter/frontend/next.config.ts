import type { NextConfig } from "next";

const apiProxyUrl = process.env.API_PROXY_URL?.replace(/\/+$/, "");

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  typescript: { tsconfigPath: process.env.NEXT_TSCONFIG_PATH ?? "tsconfig.json" },
  devIndicators: false,
  async rewrites() {
    if (!apiProxyUrl) return [];
    return [{
      source: "/api/v1/:path*",
      destination: `${apiProxyUrl}/api/v1/:path*`,
    }];
  },
};

export default nextConfig;
