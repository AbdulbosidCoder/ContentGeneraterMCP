import { useState } from 'react';
import { api, formatNumber } from '../api.js';
import PostCard from '../components/PostCard.jsx';
import { useAction, useApi } from '../hooks.js';

function useInstagramAccounts() {
  return useApi(async () => {
    const { connections } = await api.get('/connections');
    return connections.flatMap((c) => c.assets.filter((a) => a.kind === 'instagram_account').map((a) => ({ ...a, is_mock: c.is_mock })));
  });
}

function AccountSelect({ accounts, value, onChange }) {
  if (!accounts?.length) return null;
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Instagram account">
      {accounts.map((a) => <option key={a.id} value={a.id}>@{a.username}</option>)}
    </select>
  );
}

function HashtagResearch({ accounts }) {
  const [assetId, setAssetId] = useState('');
  const [hashtag, setHashtag] = useState('');
  const [edge, setEdge] = useState('top_media');
  const [result, setResult] = useState(null);
  const account = assetId || accounts?.[0]?.id;
  const quota = useApi(() => (account ? api.get('/hashtags/quota', { asset_id: account }) : Promise.resolve(null)), [account]);
  const action = useAction();

  const submit = (event) => {
    event.preventDefault();
    action.run(async () => {
      const data = await api.post('/hashtags/research', { hashtag, edge, asset_id: account });
      setResult(data);
      quota.setData(data.quota);
    });
  };

  return (
    <section className="panel">
      <h2>Hashtag research</h2>
      <p className="hint">
        Pull top or recent public posts for a hashtag. They're classified and added to your library, so plans and
        chat can learn from them.
      </p>
      {quota.data && (
        <p className="small">
          Weekly quota for @{quota.data.ig_account}: <strong>{quota.data.remaining}</strong> of {quota.data.limit} unique hashtags left
          <span className="muted"> (Instagram's limit; repeating a hashtag you already searched is free)</span>
        </p>
      )}
      <form className="row" onSubmit={submit}>
        <AccountSelect accounts={accounts} value={account} onChange={setAssetId} />
        <div className="input-prefix grow"><span>#</span>
          <input value={hashtag} onChange={(e) => setHashtag(e.target.value.replace(/^#/, ''))} placeholder="hashtag" required aria-label="Hashtag" />
        </div>
        <select value={edge} onChange={(e) => setEdge(e.target.value)} aria-label="Result type">
          <option value="top_media">Top posts</option>
          <option value="recent_media">Recent posts</option>
        </select>
        <button type="submit" disabled={action.busy || !account}>{action.busy ? 'Searching…' : 'Research'}</button>
      </form>
      {action.error && <p className="error">{action.error}</p>}
      {result && (
        <>
          <p className="small muted">{result.posts.length} posts for #{result.hashtag} · {result.classified} newly classified</p>
          <div className="post-grid compact">
            {result.posts.map((post) => <PostCard key={post.id} post={post} matched={[result.hashtag]} />)}
          </div>
        </>
      )}
    </section>
  );
}

function CompetitorResearch({ accounts }) {
  const [username, setUsername] = useState('');
  const [result, setResult] = useState(null);
  const action = useAction();
  const submit = (event) => {
    event.preventDefault();
    action.run(async () => setResult(await api.post('/competitors/research', {
      username: username.replace(/^@/, ''), asset_id: accounts?.[0]?.id,
    })));
  };
  return (
    <section className="panel">
      <h2>Competitor lookup</h2>
      <p className="hint">Works for public Instagram <strong>Business or Creator</strong> accounts only. Private and personal accounts can't be read.</p>
      <form className="row" onSubmit={submit}>
        <div className="input-prefix grow"><span>@</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="competitor username"
            pattern="@?[A-Za-z0-9._]{1,30}" required aria-label="Competitor username" />
        </div>
        <button type="submit" disabled={action.busy || !accounts?.length}>{action.busy ? 'Fetching…' : 'Analyze'}</button>
      </form>
      {action.error && <p className="error">{action.error}</p>}
      {result && (
        <>
          <div className="result-card">
            <div>
              <strong>{result.profile?.name || `@${result.username}`}</strong>
              <div className="muted small">@{result.username} · {formatNumber(result.profile?.followers_count)} followers</div>
            </div>
            <div className="stats"><div><strong>{result.posts.length}</strong><span>posts added</span></div></div>
          </div>
          <div className="post-grid compact">{result.posts.map((post) => <PostCard key={post.id} post={post} />)}</div>
        </>
      )}
    </section>
  );
}

export function HashtagSuggestions({ initialCaption = '', onPick }) {
  const [caption, setCaption] = useState(initialCaption);
  const [result, setResult] = useState(null);
  const action = useAction();
  const submit = (event) => {
    event.preventDefault();
    action.run(async () => setResult(await api.post('/hashtags/suggest', { caption, count: 12 })));
  };
  return (
    <form onSubmit={submit} className="stack-sm">
      <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={3} required
        placeholder="Paste a draft caption…" aria-label="Draft caption" />
      <div className="row">
        <button type="submit" disabled={action.busy}>{action.busy ? 'Thinking…' : 'Suggest hashtags'}</button>
        {result && <span className="small muted">based on {result.similar_posts_used} similar posts · {result.method}</span>}
      </div>
      {action.error && <p className="error">{action.error}</p>}
      {result && <SuggestionChips suggestions={result.suggestions} onPick={onPick} />}
    </form>
  );
}

function SuggestionChips({ suggestions, onPick }) {
  return (
    <div className="tags">
      {suggestions.map((s) => (
        <button key={s.hashtag} type="button" className={`tag tag-suggest source-${s.source}`} title={s.reason}
          onClick={() => (onPick ? onPick(s.hashtag) : navigator.clipboard?.writeText(`#${s.hashtag}`))}>
          #{s.hashtag}
        </button>
      ))}
      {suggestions.length === 0 && <span className="muted small">No suggestions yet. Sync more content first.</span>}
    </div>
  );
}

function MissingHashtags() {
  const missing = useApi(() => api.get('/hashtags/missing', { limit: 5 }));
  if (!missing.data || missing.data.total === 0) return null;
  return (
    <section className="panel">
      <h2>Posts published without hashtags</h2>
      <p className="hint">{missing.data.total} of your posts have no hashtags. Here's what similar posts that performed well used.</p>
      <div className="post-grid compact">
        {missing.data.posts.map(({ post, suggestions }) => (
          <PostCard key={post.id} post={post} footer={<SuggestionChips suggestions={suggestions} />} />
        ))}
      </div>
    </section>
  );
}

export default function ResearchTab() {
  const accounts = useInstagramAccounts();
  const noAccounts = accounts.data && accounts.data.length === 0;
  return (
    <div className="stack">
      {noAccounts && <p className="notice">Connect an Instagram professional account on the Accounts tab to use hashtag and competitor research.</p>}
      <div className="two-col">
        <HashtagResearch accounts={accounts.data} />
        <section className="panel">
          <h2>Hashtag suggestions</h2>
          <p className="hint">Recommendations for a draft, ranked from your similar well-performing posts. Click one to copy it.</p>
          <HashtagSuggestions />
        </section>
      </div>
      <CompetitorResearch accounts={accounts.data} />
      <MissingHashtags />
    </div>
  );
}
