import { Navigate } from "react-router-dom";

type LegacyMemoryRedirectProps = {
  to: string;
};

export function LegacyMemoryRedirect({ to }: LegacyMemoryRedirectProps) {
  return <Navigate to={to} replace />;
}
