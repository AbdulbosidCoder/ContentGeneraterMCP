import { useCallback, useEffect, useState } from 'react';
import { api, AuthError } from './api.js';
import AuthPage from './views/AuthPage.jsx';
import Shell from './views/Shell.jsx';

const params = new URLSearchParams(window.location.search);

/** Only follow same-site OAuth consent paths after login (MCP client authorization). */
function safeReturnTo(value) {
  return value && value.startsWith('/oauth/') && !value.startsWith('//') ? value : null;
}

export default function App() {
  const [authConfig, setAuthConfig] = useState(null);
  const [user, setUser] = useState(undefined);
  const returnTo = safeReturnTo(params.get('return_to'));

  const loadUser = useCallback(async () => {
    try {
      const me = await api.get('/auth/me');
      if (returnTo) {
        window.location.assign(returnTo); // continue the MCP client's authorization
        return;
      }
      setUser(me);
    } catch (err) {
      setUser(err instanceof AuthError ? null : null);
    }
  }, [returnTo]);

  useEffect(() => {
    api.get('/auth/config').then(setAuthConfig).catch(() => setAuthConfig({ demo_mode: true }));
    loadUser();
  }, [loadUser]);

  const logout = async () => {
    await api.post('/auth/logout').catch(() => {});
    window.history.replaceState(null, '', '/');
    setUser(null);
  };

  if (user === undefined || authConfig === null) {
    return <div className="boot"><span className="brand-mark pulse">✦</span></div>;
  }
  if (!user) {
    return (
      <AuthPage
        config={authConfig}
        returnTo={returnTo}
        startInSignup={params.get('signup') === '1'}
        loginError={params.get('login_error')}
        onLoggedIn={loadUser}
      />
    );
  }
  return <Shell user={user} params={params} onLogout={logout} />;
}
