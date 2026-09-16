import { useState } from 'react';
import { api, timeAgo } from '../api.js';
import { useAction, useApi } from '../hooks.js';

function CopyField({ label, value }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard?.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="copy-field">
      <span className="small muted">{label}</span>
      <div className="row">
        <code className="grow clip">{value}</code>
        <button type="button" className="ghost small" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
      </div>
    </div>
  );
}

function PersonalTokens({ tokens, reload }) {
  const [name, setName] = useState('');
  const [created, setCreated] = useState(null);
  const action = useAction();

  const create = (event) => {
    event.preventDefault();
    action.run(async () => {
      setCreated(await api.post('/mcp/tokens', { name: name || 'MCP client' }));
      setName('');
      await reload();
    });
  };

  return (
    <section className="panel">
      <h2>Connection links</h2>
      <p className="hint">
        For clients that only take a URL. The link contains a secret token that acts as you, so don't share it.
        Revoke it here if it leaks.
      </p>
      <form className="row" onSubmit={create}>
        <input className="grow" value={name} onChange={(e) => setName(e.target.value)} maxLength={100}
          placeholder="Name, e.g. Claude on my laptop" aria-label="Link name" />
        <button type="submit" disabled={action.busy}>{action.busy ? 'Creating…' : 'Create link'}</button>
      </form>
      {action.error && <p className="error">{action.error}</p>}
      {created && (
        <div className="notice stack">
          <p className="small"><strong>Copy this link now.</strong> It won't be shown again.</p>
          <CopyField label="Connector URL (Claude → Settings → Connectors → Add custom connector)" value={created.connector_url} />
          <CopyField label="Claude Code" value={created.claude_code_command} />
        </div>
      )}
      {tokens?.length === 0 && !created && <p className="muted">No connection links yet.</p>}
      <ul className="publish-list">
        {tokens?.map((token) => (
          <li key={token.id}>
            <strong className="grow">{token.name}</strong>
            <code className="small">{token.prefix}…</code>
            <span className="small muted">used {timeAgo(token.last_used_at)}</span>
            <button type="button" className="ghost small danger" disabled={action.busy}
              onClick={() => action.run(async () => {
                await api.del(`/mcp/tokens/${token.id}`);
                if (created?.id === token.id) setCreated(null);
                await reload();
              })}>
              Revoke
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function McpTab() {
  const info = useApi(() => api.get('/mcp'));
  const action = useAction();
  const data = info.data;

  return (
    <div className="stack">
      <section className="panel">
        <h2>Use your account from Claude and other MCP clients</h2>
        <p className="hint">
          Add this MCP server to an MCP client. The first time, it opens a browser window: sign in, approve access,
          and the client can then use your connected accounts (read content, research hashtags, generate plans and
          publish) as you.
        </p>
        {info.error && <p className="error">{info.error}</p>}
        {data && (
          <>
            <CopyField label="MCP server URL" value={data.mcp_url} />
            <CopyField label="Claude Code" value={data.claude_code_command} />
            <p className="small muted">
              In Claude (web or desktop), add a custom connector with the URL above.
            </p>
            {data.https_required_for_remote && (
              <p className="notice small">
                This server runs on <code>{data.mcp_url}</code>. Local clients on this machine can connect. Remote
                clients such as Claude on the web need a public HTTPS URL, so set <code>PUBLIC_BASE_URL</code> (or <code>MCP_PUBLIC_URL</code>) to your domain.
              </p>
            )}
          </>
        )}
      </section>

      <PersonalTokens tokens={data?.tokens} reload={info.reload} />

      <section className="panel">
        <h2>Authorized clients</h2>
        {action.error && <p className="error">{action.error}</p>}
        {data?.grants?.length === 0 && <p className="muted">No MCP clients have been authorized yet.</p>}
        <ul className="publish-list">
          {data?.grants?.map((grant) => (
            <li key={grant.client_id}>
              <strong className="grow">{grant.client_name}</strong>
              <span className="small muted">authorized {new Date(grant.last_authorized_at).toLocaleString()}</span>
              <button type="button" className="ghost small danger" disabled={action.busy}
                onClick={() => action.run(async () => { await api.del(`/mcp/grants/${grant.client_id}`); await info.reload(); })}>
                Revoke
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
