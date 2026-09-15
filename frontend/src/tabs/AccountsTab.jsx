import { api, apiUrl, formatNumber, labelize, timeAgo } from '../api.js';
import { useAction, useApi } from '../hooks.js';

const CONNECT_ERRORS = {
  expired: 'The connection attempt expired. Try again.',
  facebook: 'Facebook connection failed. Check that you granted access to your Pages and Instagram accounts.',
  user_denied: 'You cancelled the Facebook connection.',
  cancelled: 'You cancelled the Facebook connection.',
};

const hasActiveSync = (data) => data?.jobs?.active
  || data?.connections?.some((c) => c.assets.some((a) => ['queued', 'syncing'].includes(a.sync_status)));

export default function AccountsTab({ params, goTo }) {
  const accounts = useApi(async () => {
    const [connections, jobs] = await Promise.all([api.get('/connections'), api.get('/jobs', { limit: 12 })]);
    return { ...connections, jobs };
  }, [], { pollWhile: hasActiveSync });
  const action = useAction();

  const connected = params.get('connected');
  const connectError = params.get('connect_error');
  const data = accounts.data;

  const act = (fn) => action.run(async () => { await fn(); await accounts.reload(); });

  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Connected accounts</h2>
            <p className="hint">
              Sign in with Facebook and pick the Pages and Instagram professional accounts you manage.
              Your access tokens are stored encrypted and are only used for your account.
            </p>
          </div>
          <a className="button facebook" href={apiUrl('/connections/meta/login')}>
            {data?.connections?.length ? 'Connect another Facebook login' : 'Connect Facebook & Instagram'}
          </a>
        </div>

        {data && !data.meta_enabled && (
          <p className="notice"><span className="badge badge-mock">MOCK</span> No Meta app is configured, so connecting creates a demo account with sample Pages and posts.</p>
        )}
        {connected && <p className="success">Connected. Your content is syncing in the background.</p>}
        {connectError && <p className="error">{CONNECT_ERRORS[connectError] || `Connection failed: ${connectError}`}</p>}
        {(accounts.error || action.error) && <p className="error">{accounts.error || action.error}</p>}
        {accounts.loading && !data && <p className="muted">Loading…</p>}

        {data?.connections?.length === 0 && (
          <div className="empty-state">
            <p><strong>No accounts connected yet.</strong></p>
            <p className="muted">Instagram accounts must be Business or Creator accounts linked to a Facebook Page.</p>
          </div>
        )}

        {data?.connections?.map((connection) => (
          <div key={connection.id} className="connection">
            <div className="connection-head">
              <div>
                <strong>{connection.fb_user_name}</strong>
                {connection.is_mock && <span className="badge badge-mock">MOCK</span>}
                <span className={`status status-${connection.status}`}>{connection.status}</span>
                {connection.token_expires_at && (
                  <span className="small muted"> · access renews by reconnecting before {new Date(connection.token_expires_at).toLocaleDateString()}</span>
                )}
              </div>
              <div className="row tight">
                {connection.status === 'expired' && (
                  <a className="button small" href={apiUrl('/connections/meta/login')}>Reconnect</a>
                )}
                <button type="button" className="ghost small danger" disabled={action.busy}
                  onClick={() => window.confirm('Disconnect this Facebook login and delete its synced posts?')
                    && act(() => api.del(`/connections/${connection.id}`))}>
                  Disconnect
                </button>
              </div>
            </div>
            {connection.last_error && <p className="error small">{connection.last_error}</p>}

            <ul className="asset-list">
              {connection.assets.map((asset) => (
                <li key={asset.id} className="asset">
                  <label className="asset-toggle">
                    <input type="checkbox" checked={asset.is_selected} disabled={action.busy}
                      onChange={(e) => act(() => api.patch(`/assets/${asset.id}`, { is_selected: e.target.checked }))} />
                    <span className={`platform platform-${asset.kind}`}>{asset.kind === 'instagram_account' ? 'IG' : 'FB'}</span>
                    <span>
                      <strong>{asset.username ? `@${asset.username}` : asset.name}</strong>
                      <span className="small muted"> {asset.kind === 'instagram_account' ? 'Instagram' : 'Facebook Page'} · {formatNumber(asset.followers_count)} followers</span>
                    </span>
                  </label>
                  <div className="row tight">
                    <span className={`status status-${asset.sync_status}`} title={asset.last_error || ''}>
                      {asset.sync_status === 'ok' ? `synced ${timeAgo(asset.last_synced_at)}` : labelize(asset.sync_status)}
                    </span>
                    <button type="button" className="ghost small" disabled={action.busy || !asset.is_selected}
                      onClick={() => act(() => api.post(`/assets/${asset.id}/sync`))}>Sync now</button>
                  </div>
                  {asset.sync_status === 'error' && asset.last_error && <p className="error small full">{asset.last_error}</p>}
                </li>
              ))}
              {connection.assets.length === 0 && <li className="muted small">No Pages or Instagram accounts were shared with this app.</li>}
            </ul>
          </div>
        ))}

        {data?.connections?.length > 0 && (
          <div className="row">
            <button type="button" onClick={() => goTo('content')}>View content analysis →</button>
          </div>
        )}
      </section>

      {data?.jobs?.jobs?.length > 0 && (
        <section className="panel">
          <h2>Background activity</h2>
          <table className="table">
            <thead><tr><th>Task</th><th>Status</th><th>Result</th><th>When</th></tr></thead>
            <tbody>
              {data.jobs.jobs.map((job) => (
                <tr key={job.id}>
                  <td>{labelize(job.kind)}</td>
                  <td><span className={`status status-${job.status}`}>{job.status}</span></td>
                  <td className="small">
                    {job.error ? <span className="error-text">{job.error}</span>
                      : job.result ? Object.entries(job.result).map(([k, v]) => `${labelize(k)}: ${v}`).join(' · ') : '–'}
                  </td>
                  <td className="small muted">{timeAgo(job.finished_at || job.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
