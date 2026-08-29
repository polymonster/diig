// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  ssr: false,
  app: {
    head: {
      // Link-preview tags must be static in the HTML shell: ssr is false, and
      // scrapers (iMessage, WhatsApp, Slack, Twitter) don't run JS, so
      // useHead() in a page is invisible to them. These are the site-wide
      // defaults; scripts/og-live.mjs overrides them for /live after generate.
      title: 'diig',
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no' },
        { name: 'description', content: 'record digging' },
        { property: 'og:site_name', content: 'diig' },
        { property: 'og:type', content: 'website' },
        { property: 'og:title', content: 'diig' },
        { property: 'og:description', content: 'record digging' },
        { property: 'og:url', content: 'https://diig.app' },
        { property: 'og:image', content: 'https://diig.app/icon.png' },
        { name: 'twitter:card', content: 'summary_large_image' },
      ],
      link: [
        { rel: 'icon', type: 'image/x-icon', href: '/favicon.ico' },
        { rel: 'icon', type: 'image/png', sizes: '512x512', href: '/icon.png' },
        { rel: 'apple-touch-icon', sizes: '512x512', href: '/icon.png' },
      ],
    },
  },
  devtools: { enabled: false },

  modules: [
    '@nuxt/image',
    '@nuxt/icon',
    ['@nuxt/eslint', { config: { typescript: true } }],
    '@nuxt/test-utils',
    '@nuxtjs/tailwindcss',
    'nuxt-vuefire',
    '@pinia/nuxt',
  ],

  tailwindcss: {
    exposeConfig: true,
    viewer: true,
  },

  // Cloudflare Stream live input. Neither value is a secret — both appear in
  // every public playback URL. The ingest key lives in OBS only, never here.
  runtimeConfig: {
    public: {
      cfStreamUid:    process.env.NUXT_PUBLIC_CF_STREAM_UID    || '',
      cfCustomerCode: process.env.NUXT_PUBLIC_CF_CUSTOMER_CODE || '',
    },
  },

  vuefire: {
    auth: {
      enabled: true,
      sessionCookie: false
    },
    config: {
      apiKey: process.env.NUXT_PUBLIC_FIREBASE_API_KEY,
      authDomain: process.env.NUXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
      databaseURL: process.env.NUXT_PUBLIC_FIREBASE_DATABASE_URL,
      projectId: process.env.NUXT_PUBLIC_FIREBASE_PROJECT_ID,
      storageBucket: process.env.NUXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
      messagingSenderId: process.env.NUXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
      appId:process.env.NUXT_PUBLIC_FIREBASE_APP_ID,
      measurementId: process.env.NUXT_PUBLIC_FIREBASE_MEASUREMENT_ID,
    },
  },
})