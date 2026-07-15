import { LoaderCircle } from "lucide-react";

import { type RouteErrorSurface } from "./RouteErrorBoundary";
import styles from "./RouteLoadingShell.styles";

export type RouteLoadingLayout = "chat" | "config" | "default" | "teams";

export type RouteLoadingShellProps = {
  label?: string;
  layout?: RouteLoadingLayout;
  meta?: string;
  surface?: RouteErrorSurface;
};

function LoadingHeader({ label, meta }: { label: string; meta: string }) {
  return (
    <div className={styles.loadingHeader}>
      <span className={styles.spinnerFrame}>
        <LoaderCircle className={styles.spinner} size={18} aria-hidden="true" />
      </span>
      <span className={styles.loadingCopy}>
        <strong className={styles.title}>{label}</strong>
        <span className={styles.meta}>{meta}</span>
      </span>
    </div>
  );
}

function SkeletonLine({ compact = false }: { compact?: boolean }) {
  return <span className={compact ? styles.skeletonLineCompact : styles.skeletonLine} />;
}

function ConfigLoadingLayout() {
  return (
    <div className={styles.configGrid}>
      <aside
        data-loading-region="settings-navigation"
        className={styles.navigationPanel}
        aria-hidden="true"
      >
        <SkeletonLine compact />
        {Array.from({ length: 6 }).map((_, index) => (
          <span key={index} className={index === 0 ? styles.navigationRowActive : styles.navigationRow} />
        ))}
      </aside>
      <section
        data-loading-region="settings-content"
        className={styles.contentPanel}
        aria-hidden="true"
      >
        <div className={styles.sectionHeading}>
          <span className={styles.headingCopy}>
            <SkeletonLine />
            <SkeletonLine compact />
          </span>
          <span className={styles.headingAction} />
        </div>
        <div className={styles.configCards}>
          {Array.from({ length: 4 }).map((_, index) => (
            <span key={index} className={styles.configCard}>
              <SkeletonLine compact />
              <SkeletonLine />
              <SkeletonLine compact />
            </span>
          ))}
        </div>
      </section>
    </div>
  );
}

function ChatLoadingLayout() {
  return (
    <div className={styles.chatGrid}>
      <aside data-loading-region="chat-index" className={styles.chatIndexPanel} aria-hidden="true">
        <span className={styles.chatSearch} />
        <span className={styles.chatActions}>
          <span />
          <span />
        </span>
        {[2, 1, 1].map((rowCount, groupIndex) => (
          <span key={groupIndex} className={styles.chatIndexGroup}>
            <span className={styles.chatGroupHeading}>
              <SkeletonLine compact />
              <span className={styles.chatGroupCount} />
            </span>
            {Array.from({ length: rowCount }, (_, rowIndex) => (
              <span key={rowIndex} className={styles.chatIndexRow}>
                <span className={styles.chatAvatar} />
                <span className={styles.chatIndexCopy}>
                  <SkeletonLine compact />
                  <SkeletonLine />
                </span>
              </span>
            ))}
          </span>
        ))}
      </aside>
      <section data-loading-region="chat-workspace" className={styles.chatWorkspace} aria-hidden="true">
        <span className={styles.chatTranscript}>
          {[0, 1].map((index) => (
            <span key={index} className={styles.chatMessage}>
              <span className={styles.chatAvatar} />
              <span className={styles.chatMessageCopy}>
                <SkeletonLine compact />
                <SkeletonLine />
                <SkeletonLine compact />
              </span>
            </span>
          ))}
        </span>
        <span className={styles.chatComposer}>
          <span className={styles.chatComposerInput} />
          <span className={styles.chatComposerToolbar}>
            <span />
            <span />
          </span>
        </span>
      </section>
    </div>
  );
}

function TeamsLoadingLayout() {
  return (
    <div className={styles.teamsStack}>
      <div className={styles.statusStrip} aria-hidden="true">
        {Array.from({ length: 4 }).map((_, index) => (
          <span key={index} className={styles.statusItem}>
            <SkeletonLine compact />
          </span>
        ))}
      </div>
      <div className={styles.teamsGrid}>
        <section
          data-loading-region="team-canvas"
          className={styles.canvasPanel}
          aria-hidden="true"
        >
          <div className={styles.sectionHeading}>
            <span className={styles.headingCopy}>
              <SkeletonLine />
              <SkeletonLine compact />
            </span>
            <span className={styles.headingAction} />
          </div>
          <div className={styles.canvasBoard}>
            {Array.from({ length: 5 }).map((_, index) => (
              <span key={index} className={styles.canvasNode}>
                <span className={styles.nodeAvatar} />
                <span className={styles.nodeCopy}>
                  <SkeletonLine compact />
                  <SkeletonLine />
                </span>
              </span>
            ))}
          </div>
        </section>
        <aside
          data-loading-region="team-inspector"
          className={styles.inspectorPanel}
          aria-hidden="true"
        >
          <SkeletonLine />
          <SkeletonLine compact />
          {Array.from({ length: 4 }).map((_, index) => (
            <span key={index} className={styles.inspectorRow}>
              <SkeletonLine compact />
              <SkeletonLine />
            </span>
          ))}
        </aside>
      </div>
    </div>
  );
}

export function RouteLoadingShell({
  label,
  layout = "default",
  meta,
  surface = "workbench",
}: RouteLoadingShellProps) {
  const resolvedLabel = label ?? (
    layout === "config"
      ? "正在打开设置工作台"
      : layout === "chat"
        ? "正在打开对话工作台"
      : layout === "teams"
        ? "正在打开团队工作台"
        : surface === "launcher"
          ? "正在打开启动器"
          : "正在打开工作台"
  );
  const resolvedMeta = meta ?? (
    layout === "default" ? "加载界面模块" : "正在准备页面结构与数据区域"
  );
  const structured = layout !== "default";

  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      data-vui-app={surface}
      data-route-loading={layout}
      className={[styles.surface, structured ? styles.surfaceStructured : styles.surfaceDefault].join(" ")}
    >
      <div className={structured ? styles.structuredPanel : styles.panel}>
        <LoadingHeader label={resolvedLabel} meta={resolvedMeta} />
        {layout === "chat" ? <ChatLoadingLayout /> : null}
        {layout === "config" ? <ConfigLoadingLayout /> : null}
        {layout === "teams" ? <TeamsLoadingLayout /> : null}
      </div>
    </div>
  );
}
