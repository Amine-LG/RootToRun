import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { AppProvider } from './lib/app'
// Page code is lazy, but these shared styles must precede the theme/exercise overrides on every route.
// Loading them with a page would change the cascade (notably diagnostic widths and phone page bars).
import './pages.css'
import './components/transcript.css'
import './explore.css'
import './learn.css'
import './components/commands.css'
import './practice.css'
import './components/graph.css'
import '@fontsource-variable/figtree/wght.css'
import '@fontsource-variable/source-serif-4/wght.css'
import '@fontsource-variable/source-serif-4/wght-italic.css'
import '@fontsource-variable/jetbrains-mono/wght.css'
import './tokens.css'
import './styles.css'
import './atlas.css'
import './theme.css'
import './exercise.css'
import './lib/reveal' // installs the shared reveal policy for <details>

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </React.StrictMode>,
)
