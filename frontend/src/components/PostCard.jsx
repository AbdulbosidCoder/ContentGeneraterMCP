import { formatNumber, labelize } from '../api.js';

const FORMAT_LABELS = { REELS: 'Reel', VIDEO: 'Video', CAROUSEL_ALBUM: 'Carousel', IMAGE: 'Image', TEXT: 'Text' };
const SOURCE_LABELS = { own: 'Your post', competitor: 'Competitor', hashtag: 'Hashtag research' };

export default function PostCard({ post, matched = [], footer }) {
  const insights = post.insights || {};
  const isLink = post.permalink && !post.is_mock;
  return (
    <article className="post">
      <div className="post-meta">
        <span className={`platform platform-${post.platform === 'instagram' ? 'instagram_account' : 'facebook_page'}`}>
          {post.platform === 'instagram' ? 'IG' : 'FB'}
        </span>
        <span className="strong">{post.author ? `@${post.author}` : SOURCE_LABELS[post.source]}</span>
        {post.author && post.source !== 'own' && <span className="muted">{SOURCE_LABELS[post.source]}</span>}
        <span>{FORMAT_LABELS[post.media_type] || post.media_type}</span>
        {post.published_at && <span className="muted">{new Date(post.published_at).toLocaleDateString()}</span>}
        {post.similarity !== undefined && <span className="muted">{Math.round(post.similarity * 100)}% match</span>}
        {post.is_mock && <span className="badge badge-mock">MOCK</span>}
      </div>
      <p className="caption">{post.caption || <span className="muted">(no caption)</span>}</p>
      <div className="metrics">
        <span title="Likes">♥ {post.like_count === null ? 'hidden' : formatNumber(post.like_count)}</span>
        <span title="Comments">💬 {formatNumber(post.comments_count)}</span>
        {post.shares_count ? <span title="Shares">↗ {formatNumber(post.shares_count)}</span> : null}
        {insights.saved ? <span title="Saves">🔖 {formatNumber(insights.saved)}</span> : null}
        {insights.reach ? <span title="Reach">👁 {formatNumber(insights.reach)}</span> : null}
      </div>
      {(post.content_types?.length > 0 || post.hashtags?.length > 0) && (
        <div className="tags">
          {post.content_types?.map((type) => <span key={type} className="tag tag-type">{labelize(type)}</span>)}
          {post.hashtags?.map((tag) => (
            <span key={tag} className={`tag ${matched.includes(tag) || post.matched_hashtags?.includes(tag) ? 'tag-hit' : ''}`}>#{tag}</span>
          ))}
        </div>
      )}
      {isLink && <a className="permalink" href={post.permalink} target="_blank" rel="noreferrer noopener">Open post ↗</a>}
      {footer}
    </article>
  );
}
