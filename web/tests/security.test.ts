import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import JobCard, { safeHref } from "../src/components/JobCard"
import type { Job } from "../src/lib/supabase"
import { buildCsp } from "../src/proxy"

const job = (over: Partial<Job> = {}): Job => ({
  dedup_hash: "a".repeat(64),
  company: "Acme",
  title: "Stajyer",
  url: "https://jobs.lever.co/acme/1",
  location: "İstanbul",
  is_long_term: false,
  is_new_grad: false,
  posted_at: null,
  ...over,
})
const render = (j: Job) => renderToStaticMarkup(createElement(JobCard, { job: j }))

describe("safeHref", () => {
  it.each([
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    " javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "http://jobs.lever.co/acme/1",
    "https://user:pass@evil.com/",
    "not a url",
  ])("rejects %s", (raw) => expect(safeHref(raw)).toBeNull())

  it("accepts https", () => expect(safeHref("https://jobs.lever.co/acme/1")).toBe("https://jobs.lever.co/acme/1"))
})

describe("JobCard", () => {
  it("escapes HTML in title and company", () => {
    const html = render(job({ title: '<img src=x onerror="alert(1)">', company: "<script>x</script>" }))
    expect(html).not.toContain("<img")
    expect(html).not.toContain("<script>")
    expect(html).toContain("&lt;img")
  })

  it("external link has noopener noreferrer", () => {
    expect(render(job())).toContain('rel="noopener noreferrer"')
  })

  it("labels new-grad and long-term postings", () => {
    expect(render(job({ is_new_grad: true, is_long_term: true }))).toContain("Yeni mezun")
    expect(render(job({ is_long_term: true }))).toContain("Uzun dönem")
    expect(render(job())).not.toContain("badge")
  })

  it("renders no link for a dangerous URL", () => {
    const html = render(job({ url: "javascript:alert(1)" }))
    expect(html).not.toContain("<a")
    expect(html).not.toContain("javascript:")
  })
})

describe("CSP", () => {
  const csp = buildCsp("abc", false)
  it("production CSP has no unsafe-inline / unsafe-eval", () => {
    expect(csp).not.toContain("unsafe-inline")
    expect(csp).not.toContain("unsafe-eval")
  })
  it("blocks framing, plugins and base hijack", () => {
    expect(csp).toContain("frame-ancestors 'none'")
    expect(csp).toContain("object-src 'none'")
    expect(csp).toContain("base-uri 'self'")
  })
})

describe("secret leak guard", () => {
  const files = (dir: string): string[] =>
    readdirSync(dir).flatMap((f) => {
      const p = join(dir, f)
      return statSync(p).isDirectory() ? files(p) : [p]
    })

  it("source never references the secret key or NEXT_PUBLIC_ variables", () => {
    for (const f of files(join(__dirname, "../src"))) {
      const src = readFileSync(f, "utf8")
      expect(src, f).not.toMatch(/SECRET_KEY|sb_secret_|NEXT_PUBLIC_/)
    }
  })
})
