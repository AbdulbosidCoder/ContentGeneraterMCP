import { useState } from 'react';
import { api, formatNumber, labelize } from '../api.js';
import PostCard from '../components/PostCard.jsx';
import { useAction, useApi } from '../hooks.js';

const PAGE = 24;

export default function ContentTab({ goTo }) {
  const overview = useApi(() => api.get('/content/overview'));
  const [filters, setFilters] = useState({ source: 'own', platform: '', content_type: '', cluster_id: '', q: '', sort: 'recent' });
  const [offset, setOffset] = useState(0);
  const posts = useApi(() => api.get('/content', { ...filters, limit: PAGE, offset }), [JSON.stringify(filters), offset]);
  const classify = useAction();

  const setFilter = (key, value) => {
    setOffset(0);
    setFilters((prev) => ({ ...prev, [key]: prev[key] === value && key !== 'q' && key !== 'sort' && key !== 'source' ? '' : value }));
  };

  const data = overview.data;
  const maxEngagement = Math.max(1, ...(data?.content_types || []).map((t) => t.avg_engagement || 0));
  const clusterMax = Math.max(1, ...(data?.clusters || []).map((c) => c.avg_engagement || 0));

  if (data && data.totals.all === 0) {
    return (
      <section className="panel empty-state">
        <h2>No content yet</h2>
        <p className="muted">Connect Facebook and Instagram on the Accounts tab. Your posts sync automatically.</p>
        <button type="button" onClick={() => goTo('accounts')}>Go to Accounts</button>
      </section>
    );
  }

  return (
    <div className="stack">
      {overview.error && <p className="error">{overview.error}</p>}
      {data && (
        <>
          <div className="stat-row">
            <div className="stat"><strong>{formatNumber(data.totals.own || 0)}</strong><span>your posts</span></div>
            <div className="stat"><strong>{formatNumber(data.totals.competitor || 0)}</strong><span>competitor posts</span></div>
            <div className="stat"><strong>{formatNumber(data.totals.hashtag || 0)}</strong><span>hashtag research posts</span></div>
            <div className="stat"><strong>{data.clusters.length}</strong><span>topic clusters</span></div>
          </div>

          <div className="two-col">
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>What type of content works</h2>
                  <p className="hint">Your posts by content type, ranked by average engagement (likes + comments + shares + saves).</p>
                </div>
                <button type="button" className="ghost small" disabled={classify.busy}
                  onClick={() => classify.run(async () => { await api.post('/content/classify', { force: true }); })}>
                  {classify.busy ? 'Queued…' : 'Re-classify'}
                </button>
              </div>
              {classify.error && <p className="error">{classify.error}</p>}
              {data.unclassified_own > 0 && <p className="notice small">{data.unclassified_own} posts are still being classified.</p>}
              <ul className="bars">
                {data.content_types.map((row) => (
                  <li key={row.content_type}>
                    <button type="button" className={`bar-row ${filters.content_type === row.content_type ? 'bar-active' : ''}`}
                      onClick={() => setFilter('content_type', row.content_type)} title={data.taxonomy[row.content_type]}>
                      <span className="bar-label">{labelize(row.content_type)}</span>
                      <span className="bar-track"><span className="bar-fill" style={{ width: `${((row.avg_engagement || 0) / maxEngagement) * 100}%` }} /></span>
                      <span className="bar-value">{formatNumber(row.avg_engagement)} <span className="muted small">· {row.posts}</span></span>
                    </button>
                  </li>
                ))}
                {data.content_types.length === 0 && <li className="muted small">No classified posts yet.</li>}
              </ul>
            </section>

            <section className="panel">
              <h2>Topic clusters</h2>
              <p className="hint">Unsupervised groups of posts with similar meaning, named automatically.</p>
              <ul className="bars">
                {data.clusters.map((cluster) => (
                  <li key={cluster.id}>
                    <button type="button" className={`bar-row ${filters.cluster_id === cluster.id ? 'bar-active' : ''}`}
                      onClick={() => setFilter('cluster_id', cluster.id)} title={cluster.description || ''}>
                      <span className="bar-label">{cluster.label}</span>
                      <span className="bar-track"><span className="bar-fill alt" style={{ width: `${((cluster.avg_engagement || 0) / clusterMax) * 100}%` }} /></span>
                      <span className="bar-value">{formatNumber(cluster.avg_engagement)} <span className="muted small">· {cluster.size}</span></span>
                    </button>
                  </li>
                ))}
                {data.clusters.length === 0 && <li className="muted small">Clusters appear once at least 6 posts are synced.</li>}
              </ul>
            </section>
          </div>

          {data.top_hashtags.length > 0 && (
            <section className="panel">
              <h2>Your best hashtags</h2>
              <div className="tags">
                {data.top_hashtags.map((row) => (
                  <span key={row.hashtag} className="tag tag-stat" title={`${row.posts} posts`}>
                    #{row.hashtag} <strong>{formatNumber(row.avg_engagement)}</strong>
                  </span>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      <section className="panel">
        <div className="filters">
          <div className="segmented">
            {[['own', 'Yours'], ['competitor', 'Competitors'], ['hashtag', 'Hashtag research']].map(([value, label]) => (
              <button key={value} type="button" className={filters.source === value ? 'seg-active' : ''}
                onClick={() => setFilter('source', value)}>{label}</button>
            ))}
          </div>
          <select value={filters.platform} onChange={(e) => setFilter('platform', e.target.value)} aria-label="Platform">
            <option value="">All platforms</option>
            <option value="instagram">Instagram</option>
            <option value="facebook">Facebook</option>
          </select>
          <select value={filters.sort} onChange={(e) => setFilter('sort', e.target.value)} aria-label="Sort">
            <option value="recent">Most recent</option>
            <option value="likes">Most likes</option>
            <option value="comments">Most comments</option>
          </select>
          <input value={filters.q} onChange={(e) => setFilter('q', e.target.value)} placeholder="Search captions…" aria-label="Search" />
          {(filters.content_type || filters.cluster_id) && (
            <button type="button" className="ghost small" onClick={() => { setOffset(0); setFilters((p) => ({ ...p, content_type: '', cluster_id: '' })); }}>
              Clear {filters.content_type ? labelize(filters.content_type) : 'cluster'} filter ✕
            </button>
          )}
        </div>

        {posts.error && <p className="error">{posts.error}</p>}
        <p className="small muted">{posts.data ? `${formatNumber(posts.data.total)} posts` : 'Loading…'}</p>
        <div className="post-grid">
          {posts.data?.items.map((post) => <PostCard key={post.id} post={post} />)}
        </div>
        {posts.data && posts.data.total > PAGE && (
          <div className="row pager">
            <button type="button" className="ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Previous</button>
            <span className="small muted">{offset + 1}–{Math.min(offset + PAGE, posts.data.total)} of {posts.data.total}</span>
            <button type="button" className="ghost" disabled={offset + PAGE >= posts.data.total} onClick={() => setOffset(offset + PAGE)}>Next →</button>
          </div>
        )}
      </section>
    </div>
  );
}
