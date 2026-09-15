import { useState } from 'react';
import { api, timeAgo } from '../api.js';
import { useAction, useApi } from '../hooks.js';
import { HashtagSuggestions } from '../tabs/ResearchTab.jsx';

const pending = (data) => data?.posts?.some((p) => ['pending', 'publishing'].includes(p.status));

export default function PublishPanel() {
  const accounts = useApi(async () => {
    const { connections } = await api.get('/connections');
    return connections.flatMap((c) => c.assets.map((a) => ({ ...a, is_mock: c.is_mock })));
  });
  const posts = useApi(() => api.get('/posts'), [], { pollWhile: pending });
  const [assetId, setAssetId] = useState('');
  const [caption, setCaption] = useState('');
  const [mediaUrl, setMediaUrl] = useState('');
  const [mediaType, setMediaType] = useState('IMAGE');
  const [linkUrl, setLinkUrl] = useState('');
  const [uploadNote, setUploadNote] = useState('');
  const [showSuggest, setShowSuggest] = useState(false);
  const upload = useAction();
  const publish = useAction();

  const asset = accounts.data?.find((a) => a.id === (assetId || accounts.data?.[0]?.id));
  const isInstagram = asset?.kind === 'instagram_account';

  const onFile = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    upload.run(async () => {
      const data = await api.upload('/media', file);
      setMediaUrl(data.url);
      setMediaType(data.media_type);
      setUploadNote(data.publicly_reachable ? '' : 'This server URL is not public HTTPS, so Meta cannot download it. Real publishing needs PUBLIC_BASE_URL on a public HTTPS domain, or paste a public media URL.');
    });
  };

  const submit = (event) => {
    event.preventDefault();
    if (!window.confirm(`Publish this post to ${asset.username ? `@${asset.username}` : asset.name} now?`)) return;
    publish.run(async () => {
      await api.post('/posts', {
        asset_id: asset.id,
        caption,
        media_type: !isInstagram && !mediaUrl ? 'TEXT' : mediaType,
        media_url: mediaUrl || null,
        link_url: !isInstagram && linkUrl ? linkUrl : null,
      });
      setCaption(''); setMediaUrl(''); setLinkUrl(''); setUploadNote('');
      await posts.reload();
    });
  };

  const addHashtag = (tag) => setCaption((c) => (c.includes(`#${tag}`) ? c : `${c.trimEnd()}${c.trim() ? ' ' : ''}#${tag}`));

  if (accounts.data && accounts.data.length === 0) {
    return <section className="panel"><h2>Publish</h2><p className="muted">Connect an account first.</p></section>;
  }

  return (
    <section className="panel">
      <h2>Publish</h2>
      <p className="hint">Post to one of your Instagram accounts or Facebook Pages.</p>
      <form onSubmit={submit} className="stack-sm">
        <div className="row">
          <select value={asset?.id || ''} onChange={(e) => setAssetId(e.target.value)} aria-label="Account">
            {accounts.data?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.kind === 'instagram_account' ? `Instagram · @${a.username}` : `Facebook Page · ${a.name}`}
              </option>
            ))}
          </select>
          {asset?.is_mock && <span className="badge badge-mock">MOCK: nothing is really posted</span>}
        </div>

        <textarea rows={5} value={caption} onChange={(e) => setCaption(e.target.value)} maxLength={2200}
          placeholder={isInstagram ? 'Caption with hashtags…' : 'Post message…'} aria-label="Caption" />
        <div className="row">
          <button type="button" className="ghost small" onClick={() => setShowSuggest((s) => !s)}>
            {showSuggest ? 'Hide hashtag suggestions' : 'Suggest hashtags for this caption'}
          </button>
          <span className="small muted">{caption.length}/2200</span>
        </div>
        {showSuggest && (
          <div className="subpanel">
            <HashtagSuggestions initialCaption={caption} onPick={addHashtag} />
            <p className="small muted">Click a hashtag to add it to the caption.</p>
          </div>
        )}

        <div className="row">
          <input className="grow" type="url" value={mediaUrl} onChange={(e) => setMediaUrl(e.target.value)}
            placeholder={isInstagram ? 'Public image or video URL (required)' : 'Image URL (optional)'} aria-label="Media URL" />
          <label className="button ghost small file-button">
            {upload.busy ? 'Uploading…' : 'Upload file'}
            <input type="file" accept="image/jpeg,image/png,video/mp4,video/quicktime" onChange={onFile} hidden />
          </label>
          {isInstagram && (
            <select value={mediaType} onChange={(e) => setMediaType(e.target.value)} aria-label="Media type">
              <option value="IMAGE">Image</option>
              <option value="REELS">Reel (video)</option>
            </select>
          )}
        </div>
        {!isInstagram && (
          <input type="url" value={linkUrl} onChange={(e) => setLinkUrl(e.target.value)} placeholder="Link (optional, text posts)" aria-label="Link" />
        )}
        {uploadNote && <p className="notice small">{uploadNote}</p>}
        {(upload.error || publish.error) && <p className="error">{upload.error || publish.error}</p>}
        <div className="row">
          <button type="submit" disabled={publish.busy || !asset || (isInstagram && !mediaUrl)}>
            {publish.busy ? 'Publishing…' : 'Publish now'}
          </button>
        </div>
      </form>

      {posts.data?.posts?.length > 0 && (
        <>
          <h3 className="subhead">Recent publishing</h3>
          <ul className="publish-list">
            {posts.data.posts.map((p) => (
              <li key={p.id}>
                <span className={`status status-${p.status}`}>{p.status}</span>
                <span className="grow clip">{p.caption || p.link_url || p.media_url}</span>
                {p.is_mock && <span className="badge badge-mock">MOCK</span>}
                {p.permalink && <a href={p.permalink} target="_blank" rel="noreferrer noopener">View ↗</a>}
                <span className="small muted">{timeAgo(p.published_at || p.created_at)}</span>
                {p.error && <span className="error-text small full">{p.error}</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
