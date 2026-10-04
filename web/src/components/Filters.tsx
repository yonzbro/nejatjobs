// Düz HTML GET formu: JavaScript gerekmez, filtreler URL'de kalır (paylaşılabilir link)
const KINDS = [
  { value: "", label: "Tüm ilanlar" },
  { value: "staj", label: "Staj" },
  { value: "uzun", label: "Uzun dönem staj" },
  { value: "mezun", label: "Yeni mezun" },
] as const

export default function Filters({
  companies,
  company,
  kind,
}: {
  companies: string[]
  company: string
  kind: string
}) {
  return (
    <form method="get" className="filters">
      <select name="company" defaultValue={company} aria-label="Şirket">
        <option value="">Tüm şirketler</option>
        {companies.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
      <select name="tur" defaultValue={kind} aria-label="İlan türü">
        {KINDS.map((k) => (
          <option key={k.value} value={k.value}>
            {k.label}
          </option>
        ))}
      </select>
      <button type="submit">Filtrele</button>
    </form>
  )
}
