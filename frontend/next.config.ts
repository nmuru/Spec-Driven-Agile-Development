import type { NextConfig } from "next"; 

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_API_URL
      : "https://spec-driven-agile-development.onrender.com",
  },
};

export default nextConfig;
