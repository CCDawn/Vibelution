import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  cancelChatGPTSubscriptionLogin, chatgptSubscriptionKeys, ChatGPTSubscriptionApiError,
  fetchChatGPTSubscriptionModels, fetchChatGPTSubscriptionStatus,
  isChatGPTSubscriptionAuthorizationUrl, logoutChatGPTSubscription, startChatGPTSubscriptionLogin,
} from "../../api/chatgptSubscription";
import { openExternalUrl } from "../../api/desktopPlatform";
import type { ChatGPTSubscriptionLoginStarted, ChatGPTSubscriptionStatus } from "../../api/types/chatgptSubscription";

const SIGNED_OUT: ChatGPTSubscriptionStatus = {
  state: "signed_out", connected: false, account: null, expiresAt: null, lastError: null, login: null,
};

export function isSubscriptionLoginPending(status?: ChatGPTSubscriptionStatus) {
  return status?.login?.state === "pending" || status?.login?.state === "exchanging";
}

export function useChatGPTSubscription() {
  const queryClient = useQueryClient();
  const epoch = useRef(0);
  const [authorization, setAuthorization] = useState<ChatGPTSubscriptionLoginStarted | null>(null);
  const [manualAuthorization, setManualAuthorization] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [disconnectNotice, setDisconnectNotice] = useState<"confirmed" | "local_only" | null>(null);
  const loginMutation = useMutation({ mutationFn: startChatGPTSubscriptionLogin });
  const cancelMutation = useMutation({ mutationFn: cancelChatGPTSubscriptionLogin });
  const logoutMutation = useMutation({ mutationFn: logoutChatGPTSubscription });
  const commandPending = loginMutation.isPending || cancelMutation.isPending || logoutMutation.isPending;

  const statusQuery = useQuery({
    queryKey: chatgptSubscriptionKeys.status,
    queryFn: async ({ signal }) => {
      const version = epoch.current;
      const result = await fetchChatGPTSubscriptionStatus(signal);
      if (version !== epoch.current) throw new DOMException("Superseded", "AbortError");
      return result;
    },
    enabled: !commandPending,
    retry: false,
    refetchInterval: (query) => isSubscriptionLoginPending(query.state.data) ? 1_000 : false,
  });
  const modelsQuery = useQuery({
    queryKey: chatgptSubscriptionKeys.models,
    queryFn: async ({ signal }) => {
      const version = epoch.current;
      const result = await fetchChatGPTSubscriptionModels(signal);
      if (version !== epoch.current) throw new DOMException("Superseded", "AbortError");
      return result;
    },
    enabled: statusQuery.data?.connected === true && !commandPending && !isSubscriptionLoginPending(statusQuery.data),
    retry: false,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    const login = statusQuery.data?.login;
    if (authorization && login?.attemptId === authorization.attemptId && !isSubscriptionLoginPending(statusQuery.data)) {
      setAuthorization(null);
      setManualAuthorization(false);
    }
  }, [authorization, statusQuery.data]);

  // Leaving settings stops observers, never disconnects an authorized account.
  useEffect(() => () => { epoch.current += 1; }, []);

  const beginOperation = async () => {
    const version = ++epoch.current;
    setActionError(null);
    setDisconnectNotice(null);
    await queryClient.cancelQueries({ queryKey: chatgptSubscriptionKeys.all });
    return version;
  };
  const refresh = () => {
    setActionError(null);
    return queryClient.invalidateQueries({ queryKey: chatgptSubscriptionKeys.all });
  };

  const startLogin = async () => {
    const version = await beginOperation();
    if (version !== epoch.current) return;
    try {
      const result = await loginMutation.mutateAsync();
      if (version !== epoch.current) return;
      if (!isChatGPTSubscriptionAuthorizationUrl(result.authorizationUrl)) throw new ChatGPTSubscriptionApiError("invalid_response");
      setAuthorization(result);
      setManualAuthorization(false);
      queryClient.setQueryData<ChatGPTSubscriptionStatus>(chatgptSubscriptionKeys.status, (current) => ({
        ...(current ?? SIGNED_OUT), lastError: null,
        login: { attemptId: result.attemptId, state: "pending", expiresAt: result.expiresAt },
      }));
      void queryClient.invalidateQueries({ queryKey: chatgptSubscriptionKeys.all });
      const opened = await openExternalUrl(result.authorizationUrl);
      if (version === epoch.current) setManualAuthorization(!opened);
    } catch (error) {
      if (version === epoch.current) setActionError(error);
    }
  };

  const reopenAuthorization = async () => {
    if (!authorization) return;
    const version = epoch.current;
    const opened = await openExternalUrl(authorization.authorizationUrl);
    if (version === epoch.current) setManualAuthorization(!opened);
  };

  const cancelLogin = async () => {
    const attemptId = authorization?.attemptId ?? statusQuery.data?.login?.attemptId;
    if (!attemptId) return;
    const version = await beginOperation();
    if (version !== epoch.current) return;
    try {
      await cancelMutation.mutateAsync(attemptId);
      if (version !== epoch.current) return;
      setAuthorization(null);
      setManualAuthorization(false);
      queryClient.setQueryData<ChatGPTSubscriptionStatus>(chatgptSubscriptionKeys.status, (current) => current ? ({
        ...current, login: current.login?.attemptId === attemptId ? { ...current.login, state: "cancelled" } : current.login,
      }) : SIGNED_OUT);
      await queryClient.invalidateQueries({ queryKey: chatgptSubscriptionKeys.all });
    } catch (error) {
      if (version === epoch.current) setActionError(error);
    }
  };

  const disconnect = async () => {
    const version = await beginOperation();
    if (version !== epoch.current) return false;
    try {
      const result = await logoutMutation.mutateAsync();
      if (version !== epoch.current) return false;
      setAuthorization(null);
      setManualAuthorization(false);
      setDisconnectNotice(result.revocationConfirmed ? "confirmed" : "local_only");
      queryClient.setQueryData(chatgptSubscriptionKeys.status, SIGNED_OUT);
      queryClient.removeQueries({ queryKey: chatgptSubscriptionKeys.models });
      await queryClient.invalidateQueries({ queryKey: chatgptSubscriptionKeys.all });
      return true;
    } catch (error) {
      if (version === epoch.current) setActionError(error);
      return false;
    }
  };

  return {
    statusQuery, modelsQuery, authorization, manualAuthorization, actionError, disconnectNotice,
    pending: isSubscriptionLoginPending(statusQuery.data), commandPending,
    starting: loginMutation.isPending, cancelling: cancelMutation.isPending, disconnecting: logoutMutation.isPending,
    startLogin, reopenAuthorization, cancelLogin, disconnect, refresh,
  };
}
