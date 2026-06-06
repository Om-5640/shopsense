'use client'

/**
 * Fires once after a user's first login to merge their guest session data
 * into their authenticated account. Runs silently in the background — no UI.
 *
 * Flow:
 *   guest session (ss_xxx) → user logs in → POST /api/auth/adopt-legacy
 *   → backend re-assigns all UserSignal + ProductMemory rows to auth_xxx
 *   → flag set in localStorage so it only runs once per device
 */

import { useEffect } from 'react'
import { useSession } from 'next-auth/react'
import { getOrCreateSessionId } from '@/lib/api'

const ADOPTED_KEY = 'shopsense_legacy_adopted'

export function AdoptLegacy() {
  const { data: session, status } = useSession()

  useEffect(() => {
    if (status !== 'authenticated' || !session?.accessToken) return

    // Already adopted on this device
    if (localStorage.getItem(ADOPTED_KEY) === 'true') return

    const legacyId = getOrCreateSessionId()
    // Only meaningful if there was a real guest session (ss_ prefix)
    if (!legacyId.startsWith('ss_')) return

    fetch(
      `/api/auth/adopt-legacy?legacy_session_id=${encodeURIComponent(legacyId)}`,
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${session.accessToken}` },
      }
    )
      .then((res) => {
        if (res.ok) localStorage.setItem(ADOPTED_KEY, 'true')
      })
      .catch(() => {
        // Non-fatal — guest data stays in place, user just won't see it under their account
      })
  }, [status, session])

  return null
}
