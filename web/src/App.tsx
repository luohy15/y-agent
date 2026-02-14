import { useCallback } from "react";
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

  const handleSelectChat = useCallback((id: string | null) => {
    navigate(id ? `/${id}` : "/");
  }, [navigate]);

  const handleChatCreated = useCallback((chatId: string) => {
    navigate(`/${chatId}`);
  }, [navigate]);

  const handleLogout = useCallback(() => {
    auth.logout();
    navigate("/");
  }, [auth, navigate]);

  return (
    <div className="h-full flex flex-col">
      <Header email={auth.email} isLoggedIn={auth.isLoggedIn} gsiReady={auth.gsiReady} onLogout={handleLogout} />
      <div className="flex flex-1 min-h-0">
        <ChatList
          isLoggedIn={auth.isLoggedIn}
          selectedChatId={selectedChatId}
          onSelectChat={handleSelectChat}
        />
        <ChatView
          chatId={selectedChatId}
          onChatCreated={handleChatCreated}
        />
      </div>
    </div>
  );
}
