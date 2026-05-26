import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function fmtPrice(amount: number, currency: 'INR' | 'USD' | string) {
  if (currency === 'INR') return `₹${amount.toLocaleString('en-IN')}`
  if (currency === 'USD') return `$${amount.toFixed(2)}`
  return `${amount}`
}

export function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

export function fmtRelative(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days < 7) return `${days}d ago`
  return fmtDate(iso)
}

export function scoreGrade(pct: number): 'excellent' | 'good' | 'poor' {
  if (pct >= 70) return 'excellent'
  if (pct >= 45) return 'good'
  return 'poor'
}
