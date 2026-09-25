export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '-'
  return d.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso.slice(0, 10)
  return d.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric' })
}

export function fmtNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return '-'
  return n.toLocaleString('en-IN')
}

export function statusBadge(status: string | null | undefined): string {
  switch (status) {
    case 'ONLINE':
    case 'ACTIVE':
    case 'OK':
      return 'badge badge-ok'
    case 'DUE':
    case 'PENDING_VALIDATION':
    case 'UNKNOWN':
      return 'badge badge-warn'
    case 'FAULTY':
    case 'OFFLINE':
    case 'DECOMMISSIONED':
      return 'badge badge-crit'
    default:
      return 'badge badge-neutral'
  }
}
