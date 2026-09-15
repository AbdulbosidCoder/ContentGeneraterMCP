import { useState } from 'react';
import { api } from '../api.js';
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
                clients such as Claude on the web need a public HTTPS URL, so set <code>PUBLIC_BASE_URL</code> to your domain.
              </p>
            )}
          </>
        )}
      </section>

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
