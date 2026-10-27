// Only middleware errors about the active workspace trigger recovery. A resource
// ACL denial must never log a user out or move their request to another workspace.
export function isWorkspaceFailure(status: number, data: any): boolean {
  return (status === 409 && data?.code === 'TENANT_REQUIRED') ||
    (status === 400 && data?.error === 'Invalid target workspace ID') ||
    (status === 401 && data?.error === 'Unauthorized: invalid workspace') ||
    (status === 403 && [
      'Forbidden: not a member of the target workspace',
      'Forbidden: insufficient permissions to access target workspace',
    ].includes(data?.error))
}

export interface RecoverySession {
  token: string
  refreshToken: string
  tenantId: number
}

export interface RecoveryIO {
  current(): RecoverySession
  refresh(token: string): Promise<{ token: string; refreshToken: string }>
  me(token: string, tenantId?: number): Promise<any>
  saveTokens(tokens: { token: string; refreshToken: string }): void
  apply(snapshot: any, reset: boolean): Promise<void>
  logout(): Promise<void>
  navigate(path: string): void
}

export function createSessionRecovery(io: RecoveryIO) {
  let pending: Promise<boolean> | null = null
  let version = 0
  let navigating = false
  let workspaceLost = false

  async function run(): Promise<boolean> {
    const before = io.current()
    let ownedToken = before.token
    try {
      if (!before.refreshToken) {
        throw { response: { status: 401 } }
      }
      const tokens = await io.refresh(before.refreshToken)
      // Don't resurrect a session that was logged out/switched while refreshing.
      if (io.current().token !== before.token) return false
      io.saveTokens(tokens)
      ownedToken = tokens.token
      let snapshot: any
      try {
        snapshot = await io.me(tokens.token, before.tenantId || undefined)
      } catch (error: any) {
        if (!isWorkspaceFailure(error.response?.status, error.response?.data)) throw error
        snapshot = await io.me(tokens.token)
      }
      if (io.current().token !== tokens.token) return false
      if (!snapshot?.success || !snapshot.data?.user?.id) {
        throw new Error('Invalid session response')
      }
      const nextTenant = Number(snapshot.data.tenant?.id || 0)
      const changed = workspaceLost || nextTenant !== before.tenantId || !nextTenant
      if (changed) version++
      await io.apply(snapshot.data, changed)
      if (changed) {
        // Never replay an old POST/PUT/DELETE under a fallback tenant.
        navigating = true
        io.navigate(nextTenant ? '/onboarding/workspace?select=1' : '/onboarding/workspace')
        return false
      }
      return true
    } catch (error: any) {
      if (error.response?.status === 401) {
        // Another login/logout may have superseded this failed request.
        if (io.current().token !== ownedToken) return false
        version++
        navigating = true
        await io.logout()
        io.navigate('/login')
        return false
      }
      // Network/5xx errors are not proof that the user's session was revoked.
      throw error
    }
  }

  return {
    get version() { return version },
    get navigating() { return navigating },
    wait() { return pending || Promise.resolve(true) },
    recover(workspace = false): Promise<boolean> {
      if (navigating) return Promise.resolve(false)
      if (workspace && !workspaceLost) { workspaceLost = true; version++ }
      if (!pending) pending = run().finally(() => { pending = null; workspaceLost = false })
      return pending
    },
  }
}
