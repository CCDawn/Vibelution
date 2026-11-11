import { useCallback, useEffect, useState } from "react";

import { VButton, VDialog } from "../../components/vui";
import qrcode from "../../vendor/qrcode-generator.js";

import styles from "./MobilePairingDialog.styles";

const CONTROL_TOKEN_HEADER = "X-Vibelution-Control-Token";

// Sync with devicePairing.renderPairingQrSvg in the phone Bridge: error correction M
// (15%) keeps the code readable off a glossy screen without inflating its density,
// and margin 2 is the quiet zone scanners need around the symbol.
function renderPairingQrSvg(payload: string): string {
  const qr = qrcode(0, "M");
  qr.addData(payload);
  qr.make();
  return qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
}

export type PairingCodeResponse = {
  code: string;
  expiresAt: string;
  ttlSeconds: number;
  host: string;
  port: number;
  payload: string;
};

/**
 * The dialog mints its own authority: it reads the control token from the
 * token-exempt bootstrap endpoint and holds it only for the duration of the
 * request. Nothing here caches the token or writes it to storage.
 */
async function requestPairingCode(): Promise<PairingCodeResponse> {
  const tokenResponse = await fetch("/api/control-token", {
    headers: { Accept: "application/json" },
  });
  if (!tokenResponse.ok) {
    throw new Error(`无法读取控制令牌（${tokenResponse.status}）`);
  }
  const tokenBody = (await tokenResponse.json()) as { controlToken?: string };
  const token = String(tokenBody.controlToken ?? "").trim();
  if (!token) {
    throw new Error("控制令牌为空，请刷新工作台");
  }

  const response = await fetch("/api/mobile/pairing/code", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      [CONTROL_TOKEN_HEADER]: token,
    },
    body: "{}",
  });
  if (!response.ok) {
    throw new Error(`配对码生成失败（${response.status}）`);
  }
  return (await response.json()) as PairingCodeResponse;
}

export type MobilePairingDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lang?: string;
};

export function MobilePairingDialog({ open, onOpenChange, lang = "zh" }: MobilePairingDialogProps) {
  const zh = lang !== "en";
  const [pairing, setPairing] = useState<PairingCodeResponse | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  const refresh = useCallback(async () => {
    setPending(true);
    setError("");
    try {
      setPairing(await requestPairingCode());
    } catch (cause) {
      setPairing(null);
      setError(cause instanceof Error ? cause.message : zh ? "配对码生成失败" : "Could not create a pairing code");
    } finally {
      setPending(false);
    }
  }, [zh]);

  useEffect(() => {
    if (!open) return;
    void refresh();
  }, [open, refresh]);

  const code = pairing ? pairing.code : "";
  const expiresMinutes = pairing ? Math.max(1, Math.round(pairing.ttlSeconds / 60)) : 5;

  return (
    <VDialog
      open={open}
      onOpenChange={onOpenChange}
      title={zh ? "连接手机" : "Connect a phone"}
    >
      <div className={styles.content}>
        <p className={styles.hint}>
          {zh
            ? `在手机 App 里打开配对入口，输入下面的配对码。配对码 ${expiresMinutes} 分钟内有效，只能用一次。`
            : `Open the pairing screen in the phone app and enter the code below. It stays valid for ${expiresMinutes} minutes and works once.`}
        </p>

        {pending ? (
          <p className={styles.hint}>{zh ? "正在生成配对码…" : "Creating a pairing code…"}</p>
        ) : null}

        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}

        {code ? (
          <div className={styles.codeCard}>
            <span className={styles.codeLabel}>
              {zh ? "配对码" : "Pairing code"}
            </span>
            <span className={styles.codeValue} data-testid="mobile-pairing-code">
              {code}
            </span>
            <span className={styles.codeMeta}>
              {pairing ? `${pairing.host}:${pairing.port}` : ""}
            </span>
          </div>
        ) : null}

        {pairing ? (
<div
            className={styles.qr}
            data-testid="mobile-pairing-qr"
            // In-process render of our own payload; no external or user-controlled HTML.
            dangerouslySetInnerHTML={{ __html: renderPairingQrSvg(pairing.payload) }}
          />
        ) : null}

        {pairing ? (
          <p className={styles.payload}>
            {zh ? "扫码内容" : "Payload"}: <code>{pairing.payload}</code>
          </p>
        ) : null}

        <div className={styles.actions}>
          <VButton variant="secondary" onPress={() => onOpenChange(false)}>
            {zh ? "关闭" : "Close"}
          </VButton>
          <VButton variant="primary" onPress={() => void refresh()} isDisabled={pending}>
            {zh ? "重新生成" : "Regenerate"}
          </VButton>
        </div>
      </div>
    </VDialog>
  );
}
