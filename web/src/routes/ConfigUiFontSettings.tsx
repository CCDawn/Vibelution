/**
 * 设置页「界面外观」（ui 分区）的界面字号行 —— 单一派生基准 --vui-font-base
 * 的用户控制入口。本地偏好轨道（不进 config.toml，照 ConfigShortcutsPanel 的
 * localStorage 本地持久化先例，行上诚实标注）；渲染在 ui 分区卡片之后
 * （ConfigRoute 分支），用现有 vui 原语组装（VSettingsRow + VButton 步进器 +
 * VNativeInput 数字框），不新增 vui 组件。
 *
 * 交互口径：−/+ 步进与手输都在钳制窗口 [14,18] 内取整（默认 16）；改动即时
 * apply（documentElement 的 --vui-font-base，不动根 font-size）并持久化；
 * 本组件也订阅变更（含跨窗口 storage 事件），任何来源生效值变化即回填显示。
 */
import { useCallback, useEffect, useState } from "react";

import {
  applyUiFontBasePx,
  clampUiFontBasePx,
  MAX_UI_FONT_BASE_PX,
  MIN_UI_FONT_BASE_PX,
  readStoredUiFontBasePx,
  subscribeStoredUiFontBasePx,
  writeStoredUiFontBasePx,
} from "../app/uiFontPreference";
import { VButton, VNativeInput, VSettingsRow } from "../components/vui";
import type { ConfigCopy } from "./config/configCopy";
import styles from "./ConfigUiFontSettings.styles";

export function ConfigUiFontSettings({ copy }: { copy: ConfigCopy }) {
  const [fontBase, setFontBase] = useState(() => readStoredUiFontBasePx());
  const [draft, setDraft] = useState(() => String(readStoredUiFontBasePx()));

  useEffect(
    () =>
      subscribeStoredUiFontBasePx((px) => {
        setFontBase(px);
        setDraft(String(px));
        applyUiFontBasePx(document, px);
      }),
    [],
  );

  const commit = useCallback((next: number) => {
    const clamped = clampUiFontBasePx(next);
    setFontBase(clamped);
    setDraft(String(clamped));
    // 即时生效 + 持久化；write 经订阅者广播（AppShell 等同步，幂等跳过同值）。
    applyUiFontBasePx(document, clamped);
    writeStoredUiFontBasePx(clamped);
  }, []);

  function handleTyped(raw: string) {
    setDraft(raw);
    // 非法输入（空/非数）不提交，等 blur 回填当前生效值；越界提交时钳进窗口。
    const parsed = Number(raw);
    if (raw.trim() !== "" && Number.isFinite(parsed)) {
      commit(parsed);
    }
  }

  return (
    <VSettingsRow
      testId="ui-font-base-settings"
      label={copy.uiFontLabel}
      description={copy.uiFontDescription}
      controlLayout="wide"
      control={
        <div className={styles.stepper} data-testid="ui-font-base-stepper">
          <VButton
            variant="secondary"
            aria-label={copy.uiFontDecrease}
            isDisabled={fontBase <= MIN_UI_FONT_BASE_PX}
            onPress={() => commit(fontBase - 1)}
          >
            −
          </VButton>
          <VNativeInput
            type="number"
            min={MIN_UI_FONT_BASE_PX}
            max={MAX_UI_FONT_BASE_PX}
            step={1}
            value={draft}
            aria-label={copy.uiFontLabel}
            className={styles.stepInput}
            onChange={(event) => handleTyped(event.target.value)}
            onBlur={() => setDraft(String(fontBase))}
          />
          <span className={styles.stepUnit}>px</span>
          <VButton
            variant="secondary"
            aria-label={copy.uiFontIncrease}
            isDisabled={fontBase >= MAX_UI_FONT_BASE_PX}
            onPress={() => commit(fontBase + 1)}
          >
            +
          </VButton>
        </div>
      }
    />
  );
}
