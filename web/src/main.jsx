import React, { useState } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import Studio from './Studio.jsx'
import Boot from './Boot.jsx'
import './index.css'

// One React bundle, two experiences: the agent chat at "/", the platform Studio
// at "/platform". A Spider-Verse boot screen plays once per load before either.
function Root() {
  const isStudio = window.location.pathname.replace(/\/$/, '') === '/platform'
  const [booted, setBooted] = useState(sessionStorage.getItem('spidey_booted') === '1')
  if (!booted) {
    return <Boot label={isStudio ? 'Assembling the Studio…' : 'Waking the web…'}
      onDone={() => { sessionStorage.setItem('spidey_booted', '1'); setBooted(true) }} />
  }
  return isStudio ? <Studio /> : <App />
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
