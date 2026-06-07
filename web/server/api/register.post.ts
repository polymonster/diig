import nodemailer from 'nodemailer'

export default defineEventHandler(async (event) => {
  const { email, message } = await readBody(event)

  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    throw createError({ statusCode: 400, message: 'Invalid email address.' })
  }

  const gmailUser = process.env.GMAIL_USER
  const gmailPass = process.env.GMAIL_APP_PASSWORD

  if (!gmailUser || !gmailPass) {
    console.warn('[register] Gmail not configured (GMAIL_USER / GMAIL_APP_PASSWORD missing)')
    return { ok: true }
  }

  const transporter = nodemailer.createTransport({
    service: 'gmail',
    auth: { user: gmailUser, pass: gmailPass },
  })

  const body = message?.trim()
    ? `Email: ${email}\n\nMessage:\n${message.trim()}`
    : `Email: ${email}`

  await transporter.sendMail({
    from: gmailUser,
    to: `${gmailUser.split('@')[0]}+diig@gmail.com`,
    subject: 'diig — new registration interest',
    text: body,
  })

  return { ok: true }
})
