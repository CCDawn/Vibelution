import { Navigate, useLocation } from "react-router-dom";

export function resolveLegacyChatRoomsRedirect(search: string): string {
  const roomId = new URLSearchParams(search).get("room")?.trim() ?? "";
  if (!roomId) {
    return "/chat";
  }
  return `/chat?room=${encodeURIComponent(roomId)}`;
}

export function LegacyChatRoomsRedirect() {
  const location = useLocation();
  return <Navigate to={resolveLegacyChatRoomsRedirect(location.search)} replace />;
}
