export default defineEventHandler(async (event) => {
  const { url } = getQuery(event)
  if (!url || typeof url !== 'string') {
    throw createError({ statusCode: 400, message: 'Missing url param' })
  }

  // only proxy hardwax audio to avoid open redirect abuse
  const parsed = new URL(url)
  if (parsed.hostname !== 'media.hardwax.com' || !parsed.pathname.endsWith('.mp3')) {
    throw createError({ statusCode: 403, message: 'Only hardwax audio supported' })
  }

  const reqHeaders: Record<string, string> = {}
  const range = getRequestHeader(event, 'range')
  if (range) reqHeaders['range'] = range

  const upstream = await fetch(url, { headers: reqHeaders })
  if (!upstream.body) {
    throw createError({ statusCode: 502, message: 'No upstream body' })
  }

  setResponseStatus(event, upstream.status)
  setResponseHeader(event, 'Content-Type', upstream.headers.get('Content-Type') || 'audio/mpeg')
  setResponseHeader(event, 'Cache-Control', 'public, max-age=86400')

  const forward = ['Content-Length', 'Content-Range', 'Accept-Ranges']
  for (const h of forward) {
    const v = upstream.headers.get(h)
    if (v) setResponseHeader(event, h, v)
  }

  return sendStream(event, upstream.body)
})
