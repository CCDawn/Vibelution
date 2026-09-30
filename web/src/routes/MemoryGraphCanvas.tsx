import { VMemoryGraphCanvas, type VMemoryGraphCanvasProps } from "../components/vui";

/** Route adapter: rendering and graph interaction belong to the VUI domain renderer. */
export function MemoryGraphCanvas(props: VMemoryGraphCanvasProps) {
  return <VMemoryGraphCanvas {...props} />;
}
