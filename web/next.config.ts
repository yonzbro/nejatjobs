import type { NextConfig } from "next"

// Tüm yanıtlara (statik dosyalar dahil) eklenen sabit başlıklar. CSP nonce gerektirdiği için src/proxy.ts'te.
const nextConfig: NextConfig = {
  poweredByHeader: false, // "X-Powered-By: Next.js" sürüm/teknoloji bilgisini gizler
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ]
  },
}

export default nextConfig
