// signup: invite-only account creation. public sign-up is disabled in firebase
// auth (identity platform > user actions), so this is the only way to create an
// account. codes live in rtdb /invites and are minted by `python dig.py -invite`.
// errors use the same {error: {message}} shape as identitytoolkit so the app's
// unpack_error_response shows them unchanged.
//
// register: "register interest" form on diig.app (hosting rewrites
// /api/register here). stores to rtdb /waitlist, read with `python dig.py -waitlist`.

import { onRequest } from 'firebase-functions/v2/https'
import { initializeApp } from 'firebase-admin/app'
import { getAuth } from 'firebase-admin/auth'
import { getDatabase } from 'firebase-admin/database'
import { createHash } from 'node:crypto'

initializeApp({
  databaseURL: 'https://diig-19d4c-default-rtdb.europe-west1.firebasedatabase.app',
})

const k_attempts_per_hour = 10
const k_hour_ms = 60 * 60 * 1000

function fail(res, status, message) {
  res.status(status).json({ error: { message } })
}

// "k7qx-m2pa" / "K7QXM2PA" -> "K7QXM2PA"
function normalise_code(code) {
  return String(code || '').toUpperCase().replace(/[^A-Z0-9]/g, '')
}

function client_ip(req) {
  const fwd = req.headers['x-forwarded-for']
  if (typeof fwd === 'string' && fwd.length) {
    return fwd.split(',')[0].trim()
  }
  return req.ip || 'unknown'
}

function hash(value) {
  return createHash('sha256').update(value).digest('hex').slice(0, 32)
}

// per ip attempt counter so codes can't be brute forced. counts every attempt,
// not just failures. ips are hashed so no raw addresses are stored.
async function within_rate_limit(db, ip, bucket = 'signup') {
  const now = Date.now()
  const result = await db.ref(`signup_limits/${bucket}_${hash(ip)}`).transaction((v) => {
    if (!v || now - v.start > k_hour_ms) {
      return { start: now, count: 1 }
    }
    if (v.count >= k_attempts_per_hour) {
      return // abort
    }
    v.count += 1
    return v
  })
  return result.committed
}

// atomically claim one use of an invite. returns null on success or an error
// message. note: rtdb transactions first run against the local cache, which is
// empty, so a null value must be written back (not aborted) to force a retry
// against the real server value.
async function claim_invite(ref) {
  const now = Date.now()
  const result = await ref.transaction((inv) => {
    if (inv === null) {
      return null
    }
    if (inv.expires && now > inv.expires) {
      return // abort
    }
    if ((inv.uses || 0) >= (inv.max_uses || 1)) {
      return // abort
    }
    inv.uses = (inv.uses || 0) + 1
    return inv
  })

  const inv = result.snapshot.val()
  if (inv === null) {
    return 'INVALID_INVITE_CODE'
  }
  if (!result.committed) {
    return inv.expires && now > inv.expires ? 'INVITE_CODE_EXPIRED' : 'INVITE_CODE_USED'
  }
  return null
}

async function release_invite(ref) {
  await ref.child('uses').transaction((uses) => Math.max((uses || 1) - 1, 0))
}

const k_auth_errors = {
  'auth/email-already-exists': 'EMAIL_EXISTS',
  'auth/invalid-email': 'INVALID_EMAIL',
  'auth/invalid-password': 'WEAK_PASSWORD : Password should be at least 6 characters',
}

export const signup = onRequest(
  { region: 'europe-west1', invoker: 'public', maxInstances: 5 },
  async (req, res) => {
    if (req.method !== 'POST') {
      return fail(res, 405, 'METHOD_NOT_ALLOWED')
    }

    const { email, password, invite } = req.body || {}
    if (typeof email !== 'string' || typeof password !== 'string' || !email || !password) {
      return fail(res, 400, 'MISSING_EMAIL_OR_PASSWORD')
    }

    const code = normalise_code(invite)
    if (code.length < 6 || code.length > 32) {
      return fail(res, 400, 'INVALID_INVITE_CODE')
    }

    const db = getDatabase()

    if (!(await within_rate_limit(db, client_ip(req)))) {
      return fail(res, 429, 'TOO_MANY_ATTEMPTS_TRY_LATER')
    }

    const ref = db.ref(`invites/${code}`)
    const claim_error = await claim_invite(ref)
    if (claim_error) {
      return fail(res, 403, claim_error)
    }

    let user
    try {
      user = await getAuth().createUser({ email, password })
    }
    catch (e) {
      await release_invite(ref)
      const message = k_auth_errors[e.code]
      if (message) {
        return fail(res, 400, message)
      }
      console.error('[signup] createUser failed', e)
      return fail(res, 500, 'SIGNUP_FAILED')
    }

    await ref.child(`used_by/${user.uid}`).set({ email, at: Date.now() })
    res.status(200).json({ ok: true })
  },
)

// one entry per email, keyed by a hash since rtdb keys can't contain '.'.
// repeat submissions return ok and keep the original entry.
export const register = onRequest(
  { region: 'europe-west1', invoker: 'public', maxInstances: 2 },
  async (req, res) => {
    if (req.method !== 'POST') {
      return res.status(405).json({ message: 'Method not allowed.' })
    }

    const { email, message } = req.body || {}
    if (typeof email !== 'string' || email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return res.status(400).json({ message: 'Invalid email address.' })
    }
    const note = typeof message === 'string' ? message.trim().slice(0, 1000) : ''

    const db = getDatabase()

    if (!(await within_rate_limit(db, client_ip(req), 'register'))) {
      return res.status(429).json({ message: 'Too many attempts, please try again later.' })
    }

    const entry = { email: email.trim(), message: note, at: Date.now() }
    await db.ref(`waitlist/${hash(entry.email.toLowerCase())}`).transaction((v) => {
      if (v === null) {
        return entry
      }
      return // abort, already registered
    })

    res.status(200).json({ ok: true })
  },
)
