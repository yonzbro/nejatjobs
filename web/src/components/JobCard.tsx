import type { Job } from "@/lib/supabase"

// Veritabanı da https zorunlu tutar; burada tekrar kontrol: javascript:/data: linki asla render edilmez
export function safeHref(raw: string): string | null {
  try {
    const u = new URL(raw)
    return u.protocol === "https:" && !u.username && !u.password ? u.href : null
  } catch {
    return null
  }
}

export default function JobCard({ job }: { job: Job }) {
  const href = safeHref(job.url)
  return (
    <li className="card">
      {job.is_long_term && <span className="badge">Uzun dönem</span>}
      {/* React metni otomatik escape eder; dangerouslySetInnerHTML kullanılmaz */}
      <h2>{job.title}</h2>
      <p className="meta">
        {job.company}
        {job.location ? ` · ${job.location}` : ""}
      </p>
      {href && (
        <a href={href} target="_blank" rel="noopener noreferrer">
          İlana git →
        </a>
      )}
    </li>
  )
}
