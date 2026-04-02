import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow Next.js to transpile the local billing-ui package so that its
  // imports (lucide-react, etc.) resolve from THIS app's node_modules.
  transpilePackages: ["@platform/billing-ui"],
};

export default nextConfig;
