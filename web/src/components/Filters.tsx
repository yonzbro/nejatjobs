// Düz HTML GET formu: JavaScript gerekmez, filtreler URL'de kalır (paylaşılabilir link)
export default function Filters({
  companies,
  company,
  longTerm,
}: {
  companies: string[]
  company: string
  longTerm: boolean
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
      <label>
        <input type="checkbox" name="uzun" value="1" defaultChecked={longTerm} /> Sadece uzun dönem
      </label>
      <button type="submit">Filtrele</button>
    </form>
  )
}
