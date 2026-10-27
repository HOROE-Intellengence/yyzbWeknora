import assert from 'node:assert/strict'
import test from 'node:test'
import { createSessionRecovery, isWorkspaceFailure, type RecoveryIO } from './sessionRecovery.ts'

const failure = (status: number, error: string) => ({ response: { status, data: { error } } })
function fixture() {
  let state = { token: 'old', refreshToken: 'refresh', tenantId: 12 }
  const events: any[] = []
  const io: RecoveryIO = {
    current: () => state,
    async refresh() { events.push('refresh'); return { token: 'new', refreshToken: 'rotated' } },
    async me(_token, id) { events.push(['me', id]); return { success: true, data: { user: { id: 'user' }, tenant: { id: 12 } } } },
    saveTokens(tokens) { state = { ...state, ...tokens } },
    async apply(data, reset) { events.push(['apply', data.tenant?.id, reset]) },
    async logout() { events.push('logout'); state = { token: '', refreshToken: '', tenantId: 0 } },
    navigate(path) { events.push(['navigate', path]) },
  }
  return { io, events, setState: (value: typeof state) => { state = value } }
}

test('resource permission denial is not a workspace failure', () => {
  assert.equal(isWorkspaceFailure(403, { error: 'Forbidden' }), false)
  assert.equal(isWorkspaceFailure(404, { error: 'knowledge base not found' }), false)
  assert.equal(isWorkspaceFailure(403, { error: { message: 'insufficient role' } }), false)
  assert.equal(isWorkspaceFailure(400, { error: 'Invalid target workspace ID' }), true)
  assert.equal(isWorkspaceFailure(409, { code: 'TENANT_REQUIRED' }), true)
})

test('parallel expired requests share one refresh and may retry in same workspace', async () => {
  const f = fixture(); const r = createSessionRecovery(f.io)
  assert.deepEqual(await Promise.all([r.recover(), r.recover(), r.recover()]), [true, true, true])
  assert.equal(f.events.filter(e => e === 'refresh').length, 1)
  assert.equal(r.version, 0)
  assert.equal(r.navigating, false)
})

for (const status of [400, 403]) {
  test(`lost workspace ${status} drops header, resets cache and never replays mutation`, async () => {
    const f = fixture()
    f.io.me = async (_token, id) => {
      f.events.push(['me', id])
      if (id) throw failure(status, status === 400 ? 'Invalid target workspace ID' : 'Forbidden: not a member of the target workspace')
      return { success: true, data: { user: { id: 'user' }, tenant: { id: 8 } } }
    }
    const r = createSessionRecovery(f.io)
    const version = r.version
    assert.equal(await r.recover(true), false)
    assert.ok(r.version > version)
    assert.ok(r.navigating)
    assert.deepEqual(f.events.at(-2), ['apply', 8, true])
    assert.deepEqual(f.events.at(-1), ['navigate', '/onboarding/workspace?select=1'])
    assert.equal(f.events.includes('logout'), false)
    await r.recover(true)
    assert.equal(f.events.filter(e => e === 'refresh').length, 1)
  })
}

test('no remaining workspace goes to onboarding with valid identity', async () => {
  const f = fixture()
  f.io.me = async (_token, id) => {
    if (id) throw failure(400, 'Invalid target workspace ID')
    return { success: true, data: { user: { id: 'user' }, tenant: null, memberships: [] } }
  }
  assert.equal(await createSessionRecovery(f.io).recover(true), false)
  assert.deepEqual(f.events.at(-1), ['navigate', '/onboarding/workspace'])
  assert.equal(f.events.includes('logout'), false)
})

test('revoked refresh clears session once and navigates to login', async () => {
  const f = fixture(); f.io.refresh = async () => { throw failure(401, 'revoked') }
  const r = createSessionRecovery(f.io)
  await Promise.all([r.recover(), r.recover()])
  assert.equal(f.events.filter(e => e === 'logout').length, 1)
  assert.deepEqual(f.events.at(-1), ['navigate', '/login'])
})

test('missing refresh token does not leave pending requests hanging', async () => {
  const f = fixture(); f.setState({ token: 'old', refreshToken: '', tenantId: 12 })
  const r = createSessionRecovery(f.io)
  assert.deepEqual(await Promise.all([r.recover(), r.recover()]), [false, false])
  assert.deepEqual(f.events.at(-1), ['navigate', '/login'])
})

test('server outage is not treated as revoked credentials', async () => {
  const f = fixture(); f.io.refresh = async () => { throw failure(503, 'unavailable') }
  const r = createSessionRecovery(f.io)
  await assert.rejects(r.recover())
  assert.equal(f.events.includes('logout'), false)
  assert.equal(r.navigating, false)
})

test('late refresh cannot resurrect a logged-out session', async () => {
  const f = fixture()
  let resolve!: (tokens: { token: string; refreshToken: string }) => void
  f.io.refresh = () => new Promise(done => { resolve = done })
  const r = createSessionRecovery(f.io); const pending = r.recover()
  f.setState({ token: '', refreshToken: '', tenantId: 0 })
  resolve({ token: 'new', refreshToken: 'new-refresh' })
  assert.equal(await pending, false)
  assert.equal(f.io.current().token, '')
  assert.equal(f.events.length, 0)
})

test('late rejected refresh cannot log out a newer account', async () => {
  const f = fixture()
  let reject!: (error: any) => void
  f.io.refresh = () => new Promise((_done, fail) => { reject = fail })
  const pending = createSessionRecovery(f.io).recover()
  f.setState({ token: 'other-user', refreshToken: 'other-refresh', tenantId: 99 })
  reject(failure(401, 'revoked'))
  assert.equal(await pending, false)
  assert.equal(f.io.current().token, 'other-user')
  assert.equal(f.events.includes('logout'), false)
})
