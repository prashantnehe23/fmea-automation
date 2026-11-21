import { useState } from 'react';
import { login, setupAdmin } from '../api';

// Read a sign-in error once, then take it out of the address bar (it is only ever shown, never trusted)
function takeSignInError() {
  const url = new URL(window.location.href);
  const message = url.searchParams.get('sign_in_error') ?? '';
  if (message) {
    url.searchParams.delete('sign_in_error');
    window.history.replaceState({}, '', url.pathname + url.search);
  }
  return message.slice(0, 200);
}

// B-015: sign-in, and first-run creation of the administrator (only while no user exists).
export default function LoginPage({ status, onSignedIn }) {
  const setup = status?.setup_required;
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError]       = useState(takeSignInError);
  const [busy, setBusy]         = useState(false);
  const [setupToken, setSetupToken] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      onSignedIn(await (setup ? setupAdmin(username, password, setupToken) : login(username, password)));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const field = 'w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-blue-300';

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm bg-white rounded-2xl border border-gray-100 shadow-sm p-8">
        <div className="flex items-center gap-2.5 mb-6">
          <div className="w-9 h-9 bg-blue-600 rounded-xl flex items-center justify-center text-white text-sm font-black">FM</div>
          <div>
            <p className="font-black text-gray-900 leading-tight">FMEA Platform</p>
            <p className="text-xs text-blue-500">{setup ? 'First-time setup' : 'Sign in'}</p>
          </div>
        </div>
        {setup && (
          <p className="text-xs text-gray-500 mb-4">
            No account exists yet. Create the administrator for this installation. Use at least 10 characters for the password.
          </p>
        )}
        <label className="block text-xs font-semibold text-gray-600 mb-1" htmlFor="username">Username</label>
        <input id="username" className={`${field} mb-3`} autoFocus autoComplete="username"
               value={username} onChange={e => setUsername(e.target.value)} />
        <label className="block text-xs font-semibold text-gray-600 mb-1" htmlFor="password">Password</label>
        <input id="password" type="password" className={`${field} mb-4`}
               autoComplete={setup ? 'new-password' : 'current-password'}
               value={password} onChange={e => setPassword(e.target.value)} />
        {setup && status?.setup_token_required && (
          <>
            <label className="block text-xs font-semibold text-gray-600 mb-1" htmlFor="setup-token">Setup token</label>
            <input id="setup-token" type="password" className={`${field} mb-4`} value={setupToken} onChange={e => setSetupToken(e.target.value)} />
          </>
        )}
        {error && <p role="alert" className="text-xs text-red-600 mb-3">{error}</p>}
        <button type="submit" disabled={busy || !username.trim() || !password}
                className="w-full py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-40">
          {setup ? 'Create administrator' : 'Sign in'}
        </button>
        {!setup && status?.oidc_enabled && (
          <a href="/api/auth/oidc/login"
             className="block text-center mt-3 py-2 rounded-lg border border-blue-200 text-blue-600 text-sm font-semibold hover:bg-blue-50">
            Sign in with single sign-on
          </a>
        )}
      </form>
    </div>
  );
}
