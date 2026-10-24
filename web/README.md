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

## Code layout

Nuxt 4 single page app (`ssr: false`), Vue single file components, all TypeScript.
Nuxt auto-imports everything exported from `components/`, `composables/` and `utils/`,
which is why most files have no imports for these.

```
app/
  app.vue            shell around every page: menu, settings, player bar, debug overlay
  pages/             one file per route (index.vue is /, stores.vue is /stores ...)
  components/        reusable pieces
    AppHeader          top bar; pages put their own nav / search in its slot
    TileBase           release tile layout (art, text, icons row, track dots)
    ReleaseTile        TileBase for store releases (audio snippets, like / buy)
    DiscogsTile        TileBase for discogs results (youtube videos)
    PlayerBar          bottom player, audio and youtube
    LoadingSpinner, MarkdownPage, AppMenu, SettingsPanel, DebugOverlay
  composables/       shared state and data access (module-level refs = app-wide singletons)
    useDb              realtime database REST: get / put / patch, signed with the user's token
    useStores          store catalogue + ranked release lists
    usePlayer          playback state and controls
    useLikes, useProfile, useHomepage, useDiscogs, useLiveStatus
  utils/             plain functions and types, no state
    release.ts         the Release type and helpers (artwork, label/cat, stock tags)
    storage.ts         localStorage that never throws
    icons.ts           FontAwesome glyph names
  assets/css/main.css  global styles: fonts, colour variables, shared layout classes
  content/           markdown for faq / privacy / terms
```

Styles: shared classes live in `main.css`; everything else is in the component's own
`<style scoped>` block. Colours come from the CSS variables at the top of `main.css`.
