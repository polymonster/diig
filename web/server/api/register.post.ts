export default defineEventHandler(async (event) => {
  const { email, message } = await readBody(event)

  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    throw createError({ statusCode: 400, message: 'Invalid email address.' })
  }

  const apiKey = process.env.MAILCHIMP_API_KEY
  const audienceId = process.env.MAILCHIMP_AUDIENCE_ID

  if (!apiKey || !audienceId) {
    // Not configured yet — log and silently succeed so the UI still works during dev
    console.warn('[register] Mailchimp not configured (MAILCHIMP_API_KEY / MAILCHIMP_AUDIENCE_ID missing)')
    return { ok: true }
  }

  const dc = apiKey.split('-').pop()
  const base = `https://${dc}.api.mailchimp.com/3.0/lists/${audienceId}`
  const auth = { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' }

  const memberRes = await fetch(`${base}/members`, {
    method: 'POST',
    headers: auth,
    body: JSON.stringify({
      email_address: email,
      status: 'subscribed',
      tags: ['pending-invite'],
    }),
  })

  if (!memberRes.ok) {
    const err = await memberRes.json() as { title?: string; detail?: string }
    if (err.title !== 'Member Exists') {
      throw createError({ statusCode: 400, message: err.detail ?? 'Registration failed.' })
    }
  }

  if (message?.trim()) {
    const member = memberRes.ok ? await memberRes.json() as { id: string } : null
    // Mailchimp member id is the subscriber hash (MD5 of lowercased email)
    const hash = member?.id ?? ''
    if (hash) {
      await fetch(`${base}/members/${hash}/notes`, {
        method: 'POST',
        headers: auth,
        body: JSON.stringify({ note: message.trim() }),
      }).catch(() => {}) // notes are best-effort
    }
  }

  return { ok: true }
})
