// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  ssr: false,
  app: {
    head: {
      meta: [
        { name: 'viewport', content: 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no' },
      ],
      link: [
        { rel: 'icon', type: 'image/png', href: '/icon.png' },
        { rel: 'apple-touch-icon', href: '/icon.png' },
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