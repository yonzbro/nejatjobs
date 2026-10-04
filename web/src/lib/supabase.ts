// Yalnızca sunucuda çalışır. Değişkenlerde "public" öneki yok → tarayıcı bundle'ına girmez.
// Publishable key ile yalnızca okunur; yazma yetkisini RLS engeller (scraper/schema.sql).

export type Job = {
  dedup_hash: string
  company: string
  title: string
  url: string
  location: string | null
  is_long_term: boolean
  posted_at: string | null
}

const ACTIVE_DAYS = 2 // scraper günde 3 kez çalışır; 2 gün görülmeyen ilan kapanmış sayılır
const HOUR = 3_600_000

export async function fetchActiveJobs(): Promise<Job[]> {
  const base = process.env.SUPABASE_URL
  const key = process.env.SUPABASE_PUBLISHABLE_KEY
  if (!base || !key) throw new Error("SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY missing")

  // Saate yuvarlanır: URL saat içinde aynı kalır → fetch cache'i işe yarar
  const since = new Date(Math.floor(Date.now() / HOUR) * HOUR - ACTIVE_DAYS * 24 * HOUR)
  const url = new URL("/rest/v1/jobs", base)
  url.searchParams.set("select", "dedup_hash,company,title,url,location,is_long_term,posted_at")
  url.searchParams.set("last_seen_at", `gte.${since.toISOString()}`)
  url.searchParams.set("order", "posted_at.desc.nullslast")

  const r = await fetch(url, { headers: { apikey: key }, next: { revalidate: 600 } })
  if (!r.ok) throw new Error(`Supabase HTTP ${r.status}`)
  return r.json()
}
