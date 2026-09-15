import { useCallback, useEffect, useState } from 'react';
import { api } from '../api.js';
import PublishPanel from '../components/PublishPanel.jsx';
import Sidebar from '../components/Sidebar.jsx';
import AccountsTab from '../tabs/AccountsTab.jsx';
import ContentTab from '../tabs/ContentTab.jsx';
import McpTab from '../tabs/McpTab.jsx';
import ResearchTab from '../tabs/ResearchTab.jsx';
import ChatView from './ChatView.jsx';

const PAGES = {
  accounts: { title: 'Accounts', subtitle: 'Your connected Facebook Pages and Instagram accounts', Component: AccountsTab },
  content: { title: 'Content', subtitle: 'What your audience responds to', Component: ContentTab },
  research: { title: 'Research', subtitle: 'Hashtags and competitors', Component: ResearchTab },
  publish: { title: 'Publish', subtitle: 'Post to Instagram and Facebook', Component: () => <PublishPanel /> },
  mcp: { title: 'MCP access', subtitle: 'Use your account from Claude and other MCP clients', Component: McpTab },
};

function initialRoute(params) {
  const view = params.get('view') || params.get('tab');
  if (view && PAGES[view]) return { view, conversationId: null };
  return { view: 'chat', conversationId: params.get('c') };
}

export default function Shell({ user, params, onLogout }) {
  const [route, setRoute] = useState(() => initialRoute(params));
  const [conversations, setConversations] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Remount the chat when the user picks a conversation, but not when a new one gets its id.
  const [chatKey, setChatKey] = useState(0);

  const loadConversations = useCallback(async () => {
    try {
      setConversations((await api.get('/conversations')).conversations);
    } catch {
      /* the sidebar simply stays empty */
    }
  }, []);

  useEffect(() => { loadConversations(); }, [loadConversations]);

  const navigate = useCallback((next, { remount = true } = {}) => {
    setRoute(next);
    setSidebarOpen(false);
    if (remount) setChatKey((k) => k + 1);
    const url = new URL(window.location.href);
    url.search = next.view === 'chat' ? (next.conversationId ? `?c=${next.conversationId}` : '') : `?view=${next.view}`;
    window.history.replaceState(null, '', url);
  }, []);

  const goTo = (view) => navigate({ view, conversationId: null });

  const deleteConversation = async (id) => {
    await api.del(`/conversations/${id}`).catch(() => {});
    if (route.conversationId === id) navigate({ view: 'chat', conversationId: null });
    loadConversations();
  };

  const page = PAGES[route.view];

  return (
    <div className={`shell ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <Sidebar
        user={user}
        route={route}
        conversations={conversations}
        onNavigate={navigate}
        onDelete={deleteConversation}
        onLogout={onLogout}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="scrim" onClick={() => setSidebarOpen(false)} aria-hidden="true" />

      <div className="main">
        <header className="mobile-bar">
          <button type="button" className="icon-btn" onClick={() => setSidebarOpen(true)} aria-label="Open menu">☰</button>
          <span className="mobile-title">{page ? page.title : 'Chat'}</span>
          <button type="button" className="icon-btn" onClick={() => navigate({ view: 'chat', conversationId: null })} aria-label="New chat">✎</button>
        </header>

        {route.view === 'chat' ? (
          <ChatView
            key={chatKey}
            user={user}
            conversationId={route.conversationId}
            onCreated={(conversation) => {
              navigate({ view: 'chat', conversationId: conversation.id }, { remount: false });
              loadConversations();
            }}
            onUpdated={loadConversations}
            goTo={goTo}
          />
        ) : (
          <div className="page-scroll">
            <div className="page">
              <div className="page-head">
                <h1 className="serif">{page.title}</h1>
                <p className="muted">{page.subtitle}</p>
              </div>
              <page.Component user={user} params={params} goTo={goTo} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
