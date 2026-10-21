import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { AppProvider } from './lib/app'
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
