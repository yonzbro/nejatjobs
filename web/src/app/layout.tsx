import type { Metadata } from "next"
import "./globals.css"

export const metadata: Metadata = {
  title: "nejatjobs — Staj İlanları",
  description: "Türkiye'deki uzun dönem ve diğer staj ilanları, şirketlerin kendi kariyer sayfalarından.",
}

// Güvenlik başlıkları burada değil: CSP → src/proxy.ts, diğerleri → next.config.ts
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  )
}
