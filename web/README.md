## Package Manager

pnpm - Get here [pnpm](https://pnpm.io/)

## Environment Setup

Before running the app, create a `.env` file in the `web/` directory with the following Firebase config values:

```sh
NUXT_PUBLIC_FIREBASE_API_KEY=
NUXT_PUBLIC_FIREBASE_AUTH_DOMAIN=
NUXT_PUBLIC_FIREBASE_DATABASE_URL=
NUXT_PUBLIC_FIREBASE_PROJECT_ID=
NUXT_PUBLIC_FIREBASE_STORAGE_BUCKET=
NUXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=
NUXT_PUBLIC_FIREBASE_APP_ID=
NUXT_PUBLIC_FIREBASE_MEASUREMENT_ID=
```

To get these values:

1. Open the Firebase Console and select the **diig** project
2. Go to **Project Settings** (gear icon, top left)
3. Scroll down to **Your apps** and select the web app
4. Copy the values from the Firebase config snippet shown there

The `.env` file is gitignored and should never be committed.

## Setup

Make sure to install dependencies:

```bash
# pnpm
pnpm install
```

## Development Server

Start the development server on `http://localhost:3000`:

```bash
# pnpm
pnpm dev

pnpm dev -o (opens tab for you)
```
