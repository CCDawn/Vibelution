import { useEffect, useState } from "react";

export function useAssistantNarrowLayout() {
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.innerWidth <= 700);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 700px)");
    const update = () => setNarrow(query.matches);
    update(); query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return narrow;
}
