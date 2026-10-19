import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { InMemoryWebStorage, UserManager, WebStorageStateStore } from 'oidc-client-ts';
import { createApi, Profile } from './api';
import { Dashboard } from './Dashboard';
import './style.css';

function App() {
  const [manager, setManager] = useState<UserManager>();
  const [session, setSession] = useState<{ token: string; profile: Profile }>();
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    async function initialize() {
      const response = await fetch('/config.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('Brak konfiguracji logowania.');
      const config = await response.json();
      if (!String(config.authority).startsWith('https://')) throw new Error('Logowanie wymaga HTTPS.');
      const auth = new UserManager({
        authority: config.authority, client_id: config.clientId, redirect_uri: window.location.origin + '/',
        post_logout_redirect_uri: window.location.origin + '/', response_type: 'code', scope: 'openid profile email',
        automaticSilentRenew: false, loadUserInfo: false,
        userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
        stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
      });
      auth.events.addAccessTokenExpired(() => { if (active) { setSession(undefined); setError('Sesja wygasła. Zaloguj się ponownie.'); } });
      if (active) setManager(auth);
      if (new URLSearchParams(window.location.search).has('state')) {
        const user = await auth.signinRedirectCallback();
        window.history.replaceState({}, '', '/');
        const profile = await createApi(user.access_token)<Profile>('/me');
        if (active) setSession({ token: user.access_token, profile });
      }
    }
    initialize().catch(() => { if (active) setError('Nie udało się zalogować. Sprawdź konfigurację dostawcy tożsamości i certyfikat.'); });
    return () => { active = false; };
  }, []);
  if (session && manager) return <Dashboard api={createApi(session.token)} profile={session.profile} onLogout={() => manager.signoutRedirect()} />;
  return <main className="login"><div className="login-card"><span className="brand-mark">+</span><p className="eyebrow">PC MED / CONTROL CENTER</p><h1>Twoje komputery.<br />Pod kontrolą.</h1><p>Centralny panel zarządzania klientami, instalacjami i komunikatami.</p>{error && <p role="alert" className="error">{error}</p>}<button disabled={!manager} onClick={() => manager?.signinRedirect().catch(() => setError('Logowanie jest chwilowo niedostępne.'))}>Zaloguj się bezpiecznie →</button><small>Dostęp przez sieć prywatną · MFA według ustawień konta</small></div><div className="login-art"><span>PC MED</span><h2>Jedno miejsce.<br />Cała infrastruktura.</h2><div className="network"><i /><i /><i /><i /><i /></div></div></main>;
}

createRoot(document.getElementById('root')!).render(<App />);
