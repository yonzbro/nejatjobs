import Filters from "@/components/Filters"
import JobCard from "@/components/JobCard"
import { fetchActiveJobs, type Job } from "@/lib/supabase"

// Bu sitelerden veri çekilmez (kullanım koşulları); yalnızca kendi arama sayfalarına link verilir
const OTHER_SOURCES = [
  { name: "Youthall", url: "https://www.youthall.com/en/jobs/internship/" },
  { name: "Toptalent", url: "https://toptalent.co/is-ilanlari/staj-ilanlari" },
  { name: "anbean KAMPÜS", url: "https://anbeankampus.co/ilanlar/" },
  { name: "Kariyer.net", url: "https://www.kariyer.net/is-ilanlari/stajyer" },
  {
    name: "LinkedIn",
    url: "https://www.linkedin.com/jobs/search/?keywords=uzun%20d%C3%B6nem%20stajyer&location=T%C3%BCrkiye",
  },
]

type SearchParams = Promise<Record<string, string | string[] | undefined>>

export default async function Page({ searchParams }: { searchParams: SearchParams }) {
  const sp = await searchParams
  const company = typeof sp.company === "string" ? sp.company : ""
  const longTerm = sp.uzun === "1"

  let all: Job[] = []
  let failed = false
  try {
    all = await fetchActiveJobs()
  } catch (e) {
    console.error(e)
    failed = true
  }

  const companies = [...new Set(all.map((j) => j.company))].sort((a, b) => a.localeCompare(b, "tr"))
  const jobs = all.filter((j) => (!company || j.company === company) && (!longTerm || j.is_long_term))

  return (
    <main>
      <h1>nejatjobs</h1>
      <p className="lead">Türkiye&apos;deki staj ilanları — şirketlerin kendi kariyer sayfalarından, günde 3 kez.</p>

      <Filters companies={companies} company={company} longTerm={longTerm} />

      {failed ? (
        <p className="empty">İlanlar şu an yüklenemedi, biraz sonra tekrar deneyin.</p>
      ) : jobs.length === 0 ? (
        <p className="empty">Bu filtrelere uyan açık ilan yok.</p>
      ) : (
        <ul className="jobs">
          {jobs.map((j) => (
            <JobCard key={j.dedup_hash} job={j} />
          ))}
        </ul>
      )}

      <section className="sources">
        <h2>Diğer kaynaklar</h2>
        <p>Bu sitelerdeki ilanları kaçırmamak için kendi ilan alarmlarını kurun.</p>
        <ul>
          {OTHER_SOURCES.map((s) => (
            <li key={s.name}>
              <a href={s.url} target="_blank" rel="noopener noreferrer">
                {s.name}
              </a>
            </li>
          ))}
        </ul>
      </section>
    </main>
  )
}
