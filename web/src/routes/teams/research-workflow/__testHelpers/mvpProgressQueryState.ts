/** Shared mockable query state for panel tests (mirrors HomeRedirect.test pattern). */

type QueryState = {
  isPending: boolean;
  isError: boolean;
  error: Error | null;
  data: unknown;
  refetch: () => void;
};

const state: QueryState = {
  isPending: false,
  isError: false,
  error: null,
  data: undefined,
  refetch: () => {},
};

export const queryState = {
  current: () => state,
  set: (next: QueryState) => {
    Object.assign(state, next);
  },
  reset: () => {
    state.isPending = false;
    state.isError = false;
    state.error = null;
    state.data = undefined;
    state.refetch = () => {};
  },
};
