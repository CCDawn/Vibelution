import { useCallback, useMemo, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { postUserActionObservation } from "../../app/userActionTelemetry";
import {
  chatRouteSelectionKey,
  chatRouteSelectionsEqual,
  parseChatRouteSelection,
  serializeChatRouteSelection,
  type ChatRouteSelection,
} from "./chatSelectionProjection";

export type ChatRouteNavigateOptions = {
  /** Replace the current history entry instead of pushing a new one. */
  replace?: boolean;
  /** Optional UI entry point for user-action telemetry. */
  telemetrySource?: string;
};

export type UseChatRouteSelectionResult = {
  /** Current committed route selection (single authority for the Chat page). */
  selection: ChatRouteSelection;
  /** Navigate to a direct session; replaces by default (tab-click semantics). */
  openSession: (sessionId: string, options?: ChatRouteNavigateOptions) => void;
  /** Navigate to a group room; pushes by default. */
  openRoom: (roomId: string, options?: ChatRouteNavigateOptions) => void;
  /** Navigate to the explicit Project Agent Bus route. */
  openProjectBus: (options?: ChatRouteNavigateOptions) => void;
  /**
   * One-shot default canonicalization for a bare `/chat` entry. Each bare
   * `location.key` is canonicalized at most once; explicit targets are never
   * rewritten.
   */
  canonicalizeBareRoute: (target: ChatRouteSelection) => void;
  /**
   * Compare-and-swap transition for async lifecycle results. Navigates only
   * when the current committed route still equals `expected`; otherwise the
   * caller must update caches only.
   */
  replaceIfStillViewing: (
    expected: ChatRouteSelection,
    next: ChatRouteSelection,
  ) => boolean;
  /** True when the current committed route equals the given selection. */
  matchesSelection: (expected: ChatRouteSelection) => boolean;
};

/**
 * Sole Chat route writer.
 *
 * Business modules must not build `/chat?session=` / `/chat?room=` URLs or
 * call `navigate` for Chat selection targets directly. Async create/delete/
 * archive/reset/select results must go through `replaceIfStillViewing` so a
 * late response can never pull the user away from a page they already left.
 */
export function useChatRouteSelection(): UseChatRouteSelectionResult {
  const location = useLocation();
  const navigate = useNavigate();
  const canonicalizedBareLocationKeysRef = useRef<Set<string>>(new Set());

  const selection = useMemo(
    () => parseChatRouteSelection(location.search),
    [location.search],
  );

  const navigateToSelection = useCallback(
    (next: ChatRouteSelection, options?: ChatRouteNavigateOptions) => {
      const search = serializeChatRouteSelection(location.search, next);
      navigate({ pathname: "/chat", search }, { replace: options?.replace ?? false });
    },
    [location.search, navigate],
  );

  const openSession = useCallback(
    (sessionId: string, options?: ChatRouteNavigateOptions) => {
      const normalizedSessionId = String(sessionId || "").trim();
      if (!normalizedSessionId) {
        return;
      }
      const current = parseChatRouteSelection(location.search);
      const previousSessionId = current.kind === "session" ? current.sessionId : "";
      if (previousSessionId !== normalizedSessionId) {
        postUserActionObservation("session_open", {
          sessionId: normalizedSessionId,
          previousSessionId,
          source: String(options?.telemetrySource || "route_writer").trim() || "route_writer",
        });
      }
      navigateToSelection(
        { kind: "session", sessionId: normalizedSessionId },
        { replace: options?.replace ?? true },
      );
    },
    [location.search, navigateToSelection],
  );

  const openRoom = useCallback(
    (roomId: string, options?: ChatRouteNavigateOptions) => {
      const normalizedRoomId = String(roomId || "").trim();
      if (!normalizedRoomId) {
        return;
      }
      const current = parseChatRouteSelection(location.search);
      postUserActionObservation("group_room_open", {
        roomId: normalizedRoomId,
        previousRouteKind: current.kind,
        source: String(options?.telemetrySource || "route_writer").trim() || "route_writer",
      });
      navigateToSelection(
        { kind: "room", roomId: normalizedRoomId },
        { replace: options?.replace ?? false },
      );
    },
    [location.search, navigateToSelection],
  );

  const openProjectBus = useCallback(
    (options?: ChatRouteNavigateOptions) => {
      const current = parseChatRouteSelection(location.search);
      postUserActionObservation("project_bus_open", {
        previousRouteKind: current.kind,
        source: String(options?.telemetrySource || "route_writer").trim() || "route_writer",
      });
      navigateToSelection({ kind: "project_bus" }, { replace: options?.replace ?? false });
    },
    [location.search, navigateToSelection],
  );

  const postRouteOpenObservation = useCallback(
    (target: ChatRouteSelection, source: string) => {
      const normalizedSource = String(source || "").trim() || "route_writer";
      if (target.kind === "session") {
        postUserActionObservation("session_open", {
          sessionId: target.sessionId,
          previousSessionId: "",
          source: normalizedSource,
        });
        return;
      }
      if (target.kind === "room") {
        postUserActionObservation("group_room_open", {
          roomId: target.roomId,
          previousRouteKind: "bare",
          source: normalizedSource,
        });
        return;
      }
      if (target.kind === "project_bus") {
        postUserActionObservation("project_bus_open", {
          previousRouteKind: "bare",
          source: normalizedSource,
        });
      }
    },
    [],
  );

  const canonicalizeBareRoute = useCallback(
    (target: ChatRouteSelection) => {
      const current = parseChatRouteSelection(location.search);
      if (current.kind !== "bare") {
        return;
      }
      if (target.kind === "bare" || target.kind === "invalid") {
        return;
      }
      if (canonicalizedBareLocationKeysRef.current.has(location.key)) {
        return;
      }
      canonicalizedBareLocationKeysRef.current.add(location.key);
      postRouteOpenObservation(target, "bare_route_bootstrap");
      navigateToSelection(target, { replace: true });
    },
    [location.key, location.search, navigateToSelection, postRouteOpenObservation],
  );

  const matchesSelection = useCallback(
    (expected: ChatRouteSelection) => {
      const current = parseChatRouteSelection(location.search);
      return chatRouteSelectionsEqual(current, expected);
    },
    [location.search],
  );

  const replaceIfStillViewing = useCallback(
    (expected: ChatRouteSelection, next: ChatRouteSelection): boolean => {
      const current = parseChatRouteSelection(location.search);
      if (!chatRouteSelectionsEqual(current, expected)) {
        return false;
      }
      if (next.kind === "session") {
        const previousSessionId = expected.kind === "session" ? expected.sessionId : "";
        if (previousSessionId !== next.sessionId) {
          postUserActionObservation("session_open", {
            sessionId: next.sessionId,
            previousSessionId,
            source: "replace_if_still_viewing",
          });
        }
      } else if (next.kind === "room") {
        postUserActionObservation("group_room_open", {
          roomId: next.roomId,
          previousRouteKind: expected.kind,
          source: "replace_if_still_viewing",
        });
      } else if (next.kind === "project_bus") {
        postUserActionObservation("project_bus_open", {
          previousRouteKind: expected.kind,
          source: "replace_if_still_viewing",
        });
      }
      const search = serializeChatRouteSelection(location.search, next);
      navigate({ pathname: "/chat", search }, { replace: true });
      return true;
    },
    [location.search, navigate],
  );

  return {
    selection,
    openSession,
    openRoom,
    openProjectBus,
    canonicalizeBareRoute,
    replaceIfStillViewing,
    matchesSelection,
  };
}

export { chatRouteSelectionKey };
