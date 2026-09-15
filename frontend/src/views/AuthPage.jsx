import { useEffect, useState } from 'react';
import { api, apiUrl } from '../api.js';
import { useAction } from '../hooks.js';

const LOGIN_ERRORS = {
  expired: 'Your Facebook login took too long. Please try again.',
  facebook: "We couldn't complete the Facebook login. Please try again.",
  cancelled: 'Facebook login was cancelled.',
  user_denied: 'Facebook login was cancelled.',
  access_denied: 'Facebook login was cancelled.',
};

function FacebookIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M24 12.07C24 5.41 18.63 0 12 0S0 5.4 0 12.07C0 18.1 4.39 23.1 10.13 24v-8.44H7.08v-3.49h3.05V9.41c0-3.02 1.8-4.7 4.54-4.7 1.31 0 2.68.24 2.68.24v2.97h-1.5c-1.5 0-1.96.93-1.96 1.89v2.26h3.33l-.53 3.5h-2.8V24C19.62 23.1 24 18.1 24 12.07z" />
    </svg>
  );
}

function SignupForm({ onDone }) {
  const [info, setInfo] = useState(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const load = useAction();
  const submit = useAction();

  useEffect(() => {
    load.run(async () => {
      const data = await api.get('/auth/signup');
      setInfo(data);
      setName(data.name?.replace(/^\[MOCK\]\s*/, '') || '');
      setEmail(data.email || '');
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSubmit = (event) => {
    event.preventDefault();
    submit.run(async () => {
      const result = await api.post('/auth/signup', { name: name.trim(), email: email.trim() });
      await onDone(result.return_to);
    });
  };

  if (load.error) {
    return (
      <>
        <p className="auth-error">{load.error}</p>
        <a className="btn btn-primary btn-block" href="/">Back to sign in</a>
      </>
    );
  }
  if (!info) return <p className="muted center">Loading…</p>;

  return (
    <form onSubmit={onSubmit} className="auth-form">
      <div className="fb-identity">
        {info.picture_url ? <img src={info.picture_url} alt="" referrerPolicy="no-referrer" />
          : <span className="avatar-initial">{(info.name || '?').replace(/^\[MOCK\]\s*/, '').charAt(0).toUpperCase()}</span>}
        <div>
          <strong>Facebook account connected</strong>
          <span className="muted small">{info.name}{info.is_mock && <span className="badge badge-mock">DEMO</span>}</span>
        </div>
      </div>
      <label className="field">
        <span>Full name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} autoComplete="name" autoFocus />
      </label>
      <label className="field">
        <span>Email</span>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required maxLength={320}
          placeholder="you@gmail.com" autoComplete="email" />
      </label>
      {submit.error && <p className="auth-error">{submit.error}</p>}
      <button type="submit" className="btn btn-primary btn-block" disabled={submit.busy}>
        {submit.busy ? 'Creating your account…' : 'Create account'}
      </button>
      <p className="fine-print">We'll use your Facebook access only to read and publish content for the Pages and Instagram accounts you choose.</p>
    </form>
  );
}

export default function AuthPage({ config, returnTo, startInSignup, loginError, onLoggedIn }) {
  const [mode, setMode] = useState(startInSignup ? 'signup' : 'login');
  const [demoName, setDemoName] = useState('');
  const demo = useAction();

  const finish = async (target) => {
    const next = returnTo || (target && target.startsWith('/oauth/') ? target : null);
    if (next) {
      window.location.assign(next);
      return;
    }
    window.history.replaceState(null, '', '/');
    await onLoggedIn();
  };

  const demoLogin = (event) => {
    event.preventDefault();
    demo.run(async () => {
      const result = await api.post('/auth/demo-facebook', { name: demoName.trim(), return_to: returnTo });
      if (result.status === 'signup_required') setMode('signup');
      else await finish();
    });
  };

  const facebookHref = apiUrl(`/auth/facebook/login${returnTo ? `?return_to=${encodeURIComponent(returnTo)}` : ''}`);

  return (
    <div className="auth">
      <div className="auth-card">
        <div className="auth-head">
          <span className="brand-mark big">✦</span>
          <h1 className="serif">{mode === 'signup' ? 'Almost there' : 'Your content, with a strategist'}</h1>
          <p className="muted">
            {mode === 'signup'
              ? "This Facebook account is new here. Tell us who you are to finish creating your account."
              : 'Sign in with the Facebook account that manages your Pages and Instagram. Returning users go straight in.'}
          </p>
          {returnTo && mode === 'login' && <p className="auth-note">Sign in to finish connecting your MCP client.</p>}
        </div>

        {mode === 'signup' ? (
          <SignupForm onDone={finish} />
        ) : (
          <>
            {loginError && <p className="auth-error">{LOGIN_ERRORS[loginError] || 'Sign-in failed. Please try again.'}</p>}
            {config.facebook_enabled && (
              <a className="btn btn-facebook btn-block" href={facebookHref}><FacebookIcon /> Continue with Facebook</a>
            )}
            {config.demo_mode && (
              <form onSubmit={demoLogin} className="auth-form">
                <p className="auth-note">
                  <span className="badge badge-mock">DEMO</span> No Meta app is configured, so this stands in for
                  Facebook Login. The same name signs you back in; a new name creates a new account.
                </p>
                <label className="field">
                  <span>Facebook name</span>
                  <input value={demoName} onChange={(e) => setDemoName(e.target.value)} required maxLength={80}
                    placeholder="e.g. Coffee Roasters" autoFocus />
                </label>
                {demo.error && <p className="auth-error">{demo.error}</p>}
                <button type="submit" className="btn btn-facebook btn-block" disabled={demo.busy}>
                  <FacebookIcon /> {demo.busy ? 'Signing in…' : 'Continue with Facebook'}
                </button>
              </form>
            )}
          </>
        )}
      </div>
    </div>
  );
}
