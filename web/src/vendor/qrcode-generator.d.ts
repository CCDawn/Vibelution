// Minimal typing for the MIT qrcode-generator vendor bundle (Kazuhiko Arase).
// Only the surface the workbench uses is declared; the vendor file stays untouched.
export type QrSvgOptions = { cellSize?: number; margin?: number; scalable?: boolean };

export type QrCode = {
  addData(data: string): void;
  make(): void;
  createSvgTag(options?: QrSvgOptions): string;
};

declare function qrcode(typeNumber: number, errorCorrectionLevel: string): QrCode;

export default qrcode;
