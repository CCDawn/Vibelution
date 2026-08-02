import { useEffect, useMemo, useState } from "react";

import styles from "./AppShellTopClock.styles";

type AppShellTopClockProps = {
  lang: "zh" | "en" | string;
  systemTimeLabel: string;
};

/**
 * Owns the 1s clock tick in isolation so AppShell + route Outlet are not
 * re-rendered every second (whole-shell flicker).
 */
export function AppShellTopClock({ lang, systemTimeLabel }: AppShellTopClockProps) {
  const [clockNow, setClockNow] = useState(() => Date.now());
  const locale = lang === "zh" ? "zh-CN" : "en-US";
  const timezone = useMemo(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || (lang === "en" ? "Local time" : "本地时间"),
    [lang],
  );
  const clockFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        weekday: "long",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: true,
      }),
    [locale],
  );
  const currentTime = clockFormatter.format(clockNow);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClockNow(Date.now());
    }, 1_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className={styles.topClock} title={timezone} aria-label={`${systemTimeLabel}: ${currentTime}`}>
      <span className={`${styles.statusDot} ${styles.status_idle}`} />
      <span>{currentTime}</span>
    </div>
  );
}
