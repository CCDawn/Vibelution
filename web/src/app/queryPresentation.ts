export type QueryPresentation =
  | "initial-loading"
  | "loaded"
  | "refreshing"
  | "error-empty"
  | "error-with-data";

export type QueryPresentationInput = {
  hasData: boolean;
  isError: boolean;
  isFetching: boolean;
  isPending: boolean;
};

export function deriveQueryPresentation({
  hasData,
  isError,
  isFetching,
  isPending,
}: QueryPresentationInput): QueryPresentation {
  if (isError) {
    return hasData ? "error-with-data" : "error-empty";
  }
  if (!hasData && isPending) {
    return "initial-loading";
  }
  if (hasData && isFetching) {
    return "refreshing";
  }
  return "loaded";
}
