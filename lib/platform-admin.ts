/**
 * Platform admin allowlist (comma-separated Clerk user IDs).
 * Must match backend `ADMIN_CLERK_USER_IDS`. Optional on the Next.js host:
 * when unset, server layouts skip role-based redirects and the app relies on
 * `/api/admin/session` + API authorization (defense in depth — set this in production).
 */
export function getPlatformAdminUserIds(): Set<string> {
  const raw = process.env.ADMIN_CLERK_USER_IDS ?? ''
  return new Set(raw.split(',').map((s) => s.trim()).filter(Boolean))
}

export function isPlatformAdminListConfigured(): boolean {
  return getPlatformAdminUserIds().size > 0
}

export function isPlatformAdminUserId(userId: string | null | undefined): boolean {
  if (!userId) return false
  const ids = getPlatformAdminUserIds()
  if (ids.size === 0) return false
  return ids.has(userId)
}
