import type { NextConfig } from "next";
const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  typescript: { tsconfigPath: process.env.NEXT_TSCONFIG_PATH ?? "tsconfig.json" },
  devIndicators: false,
};
export default nextConfig;
