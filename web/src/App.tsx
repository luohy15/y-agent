import { useCallback, useState } from "react";
import { useParams, useNavigate } from "react-router";
import { useAuth } from "./hooks/useAuth";
import Header from "./components/Header";
import ChatList from "./components/ChatList";
import ChatView from "./components/ChatView";

export default function App() {
  const auth = useAuth();
  const { chatId: urlChatId } = useParams<{ chatId: string }>();
  const navigate = useNavigate();
  const selectedChatId = urlChatId || null;
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleSelectChat = useCallback((id: string | null) => {
    navigate(id ? `/${id}` : "/");
    setSidebarOpen(false);
  }, [navigate]);

  const handleChatCreated = useCallback((chatId: string) => {
    navigate(`/${chatId}`);
    setSidebarOpen(false);
  }, [navigate]);

  const handleLogout = useCallback(() => {
    auth.logout();
    navigate("/");
  }, [auth, navigate]);

  return (
    <div className="h-dvh flex flex-col">
      <Header key={String(auth.isLoggedIn)} email={auth.email} isLoggedIn={auth.isLoggedIn} gsiReady={auth.gsiReady} onLogout={handleLogout} onToggleSidebar={() => setSidebarOpen((v) => !v)} onClickLogo={() => handleSelectChat(null)} />
      <div className="flex flex-1 min-h-0 relative">
        {/* Mobile overlay backdrop */}
        {sidebarOpen && (
          <div className="fixed inset-0 bg-black/40 z-20 md:hidden" onClick={() => setSidebarOpen(false)} />
        )}
        <div className={`
          fixed inset-y-0 left-0 z-30 w-80 transform transition-transform duration-200 md:relative md:translate-x-0 md:z-auto
          ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}
        `}>
          <ChatList
            isLoggedIn={auth.isLoggedIn}
            selectedChatId={selectedChatId}
            onSelectChat={handleSelectChat}
          />
        </div>
        <ChatView
          chatId={selectedChatId}
          onChatCreated={handleChatCreated}
        />
      </div>
    </div>
  );
}
