import PostCard from './PostCard.jsx';

export default function ExampleList({ examples, defaultOpen = false }) {
  if (!examples) return null;
  return (
    <details className="examples" open={defaultOpen}>
      <summary>Grounded in {examples.length} retrieved post{examples.length === 1 ? '' : 's'}</summary>
      {examples.length === 0 ? (
        <p className="muted">No synced posts matched. Connect and sync an account first.</p>
      ) : (
        <div className="post-grid compact">
          {examples.map((post) => <PostCard key={post.id} post={post} />)}
        </div>
      )}
    </details>
  );
}
