import styles from "./PageFrameLoadingShell.styles";

type FramePane = "rows" | "checks" | "lines" | "tasks" | "short" | "handle";

export type PageFrameLayout =
  | "agents"
  | "aux"
  | "companions"
  | "evolution"
  | "evolution-library"
  | "evolution-runs"
  | "git"
  | "kernel"
  | "launcher"
  | "launcher-tools"
  | "logs"
  | "memory-browse"
  | "memory-cards"
  | "memory-graph"
  | "memory-knowledge"
  | "memory-ops"
  | "pet"
  | "prompts"
  | "reset"
  | "review"
  | "skills"
  | "tools"
  | "usage";

export type MemoryBodyKind = "personal" | "cards" | "graph" | "knowledge" | "ops";

function Rows({ count, rowClass }: { count: number; rowClass: string }) {
  return (
    <div className={styles.rowStack}>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className={rowClass}>
          <span className={styles.boneTitle} />
          <span className={styles.boneMeta} />
        </div>
      ))}
    </div>
  );
}

function CheckRows({ count }: { count: number }) {
  return (
    <div className={styles.rowStack}>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className={styles.checkRow}>
          <span className={styles.check} />
          <span className={styles.boneTitle} />
        </div>
      ))}
    </div>
  );
}

function Lines({ count }: { count: number }) {
  return (
    <div className={styles.lineStack}>
      {Array.from({ length: count }, (_, index) => (
        <span key={index} className={index === count - 1 ? styles.boneShort : styles.boneLine} />
      ))}
    </div>
  );
}

function RouteHeaderSlot() {
  return (
    <div className={styles.header}>
      <span className={styles.headerCopy}>
        <span className={styles.boneEyebrow} />
        <span className={styles.boneTitle} />
      </span>
      <span className={styles.headerAction} />
    </div>
  );
}

function SplitBody({
  className,
  region,
  panes,
}: {
  className: string;
  region: string;
  panes: FramePane[];
}) {
  return (
    <div className={className} data-loading-region={region}>
      {panes.map((pane, index) => {
        if (pane === "handle") {
          return <span key={index} aria-hidden="true" />;
        }
        return (
          <div key={index} className={styles.pane}>
            {pane === "rows" ? <Rows count={6} rowClass={styles.row52} /> : null}
            {pane === "checks" ? <CheckRows count={6} /> : null}
            {pane === "short" ? <Rows count={6} rowClass={styles.row56} /> : null}
            {pane === "tasks" ? <Rows count={6} rowClass={styles.row72} /> : null}
            {pane === "lines" ? <Lines count={5} /> : null}
          </div>
        );
      })}
    </div>
  );
}

function FramedSplit({
  region,
  className,
  panes,
}: {
  region: string;
  className: string;
  panes: FramePane[];
}) {
  return (
    <div className={styles.page}>
      <RouteHeaderSlot />
      <SplitBody className={className} region={region} panes={panes} />
    </div>
  );
}

export function MemoryBodyLoading({ kind }: { kind: MemoryBodyKind }) {
  if (kind === "cards") {
    return (
      <div className={styles.memoryCards} data-loading-region="memory-cards">
        {Array.from({ length: 6 }, (_, index) => (
          <div key={index} className={styles.memoryCard}>
            <span className={styles.boneTitle} />
            <span className={styles.boneShort} />
          </div>
        ))}
      </div>
    );
  }
  if (kind === "graph") {
    return (
      <div className={styles.canvas} data-loading-region="memory-graph">
        <span className={styles.boneTitle} />
      </div>
    );
  }
  if (kind === "knowledge") {
    return (
      <SplitBody
        className={styles.memoryKnowledge}
        region="memory-knowledge"
        panes={["rows", "lines", "lines"]}
      />
    );
  }
  if (kind === "ops") {
    return (
      <div className={styles.pane} data-loading-region="memory-ops">
        <Rows count={6} rowClass={styles.row52} />
      </div>
    );
  }
  return (
    <SplitBody
      className={styles.memoryPersonal}
      region="memory-personal"
      panes={["short", "tasks", "lines"]}
    />
  );
}

function MemoryFrame({ kind }: { kind: MemoryBodyKind }) {
  return (
    <div className={styles.pageStack}>
      <div className={styles.tabStrip} data-loading-region="memory-subnav">
        {Array.from({ length: 5 }, (_, index) => (
          <span key={index} className={styles.tab} />
        ))}
      </div>
      <MemoryBodyLoading kind={kind} />
    </div>
  );
}

export function CompanionCardSkeleton() {
  return (
    <article className={styles.companionCard} data-loading-region="companions-card">
      <div className={styles.companionCopy}>
        <span className={styles.boneEyebrow} />
        <span className={styles.companionTitle} />
        <span className={styles.companionSubtitle} />
        <span className={styles.companionNow} />
        <div className={styles.companionStrip}>
          <span className={styles.boneShort} />
          <span className={styles.boneShort} />
          <span className={styles.boneShort} />
        </div>
      </div>
      <div className={styles.companionPortrait} />
    </article>
  );
}

function CompanionsFrame() {
  return (
    <div className={styles.companionRoute} data-loading-region="companions-workspace">
      <div className={styles.companionHero}>
        <div className={styles.companionHeroCopy}>
          <span className={styles.boneEyebrow} />
          <span className={styles.companionTitle} />
          <span className={styles.companionSubtitle} />
        </div>
      </div>
      <div className={styles.companionGrid}>
        <CompanionCardSkeleton />
      </div>
    </div>
  );
}

function UsageFrame() {
  return (
    <div className={styles.usagePage} data-loading-region="usage-workspace">
      <div className={styles.usageSheet}>
        <div className={styles.usageBreadcrumb}>
          <span className={styles.boneTitle} />
        </div>
        <RouteHeaderSlot />
        <div className={styles.usageRange}>
          <span className={styles.boneTitle} />
          <span className={styles.boneMeta} />
        </div>
        <section className={styles.usageMetrics}>
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className={styles.usageMetric}>
              <span className={styles.boneMeta} />
              <span className={styles.usageValue} />
            </div>
          ))}
        </section>
        <div className={styles.rowStack}>
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className={styles.row44}>
              <span className={styles.boneTitle} />
              <span className={styles.boneMeta} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function PetFrame() {
  return (
    <div className={styles.page} data-loading-region="pet-workspace">
      <RouteHeaderSlot />
      <div className={styles.pane}>
        <div className={styles.petMetrics}>
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className={styles.petCard}>
              <span className={styles.boneTitle} />
              <span className={styles.boneMeta} />
            </div>
          ))}
        </div>
        <div className={styles.petStatus}>
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className={styles.petStatusCard}>
              <Lines count={4} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ResetFrame() {
  return (
    <div className={styles.page} data-loading-region="reset-workspace">
      <RouteHeaderSlot />
      <div className={styles.pane}>
        <div className={styles.resetStatus}>
          <span className={styles.check} />
          <span className={styles.boneTitle} />
        </div>
        <div className={styles.resetCard}>
          <span className={styles.boneTitle} />
          <span className={styles.boneLine} />
        </div>
        <div className={styles.resetCard}>
          <span className={styles.boneTitle} />
          <span className={styles.boneShort} />
        </div>
      </div>
    </div>
  );
}

function LauncherFrame() {
  return (
    <div className={styles.pageStack} data-loading-region="launcher-workspace">
      <div className={styles.pane}>
        <Rows count={6} rowClass={styles.row44} />
      </div>
    </div>
  );
}

export function PageFrameLoading({ layout }: { layout: PageFrameLayout }) {
  switch (layout) {
    case "agents":
      return (
        <FramedSplit
          region="agents-workspace"
          className={styles.agentsSplit}
          panes={["rows", "lines", "lines"]}
        />
      );
    case "skills":
      return (
        <FramedSplit region="skills-workspace" className={styles.skillsSplit} panes={["checks", "lines"]} />
      );
    case "prompts":
      return (
        <FramedSplit region="prompts-workspace" className={styles.promptsSplit} panes={["checks", "lines"]} />
      );
    case "kernel":
      return (
        <div className={styles.page}>
          <RouteHeaderSlot />
          <div className={styles.kernelSplit} data-loading-region="kernel-workspace">
            <div className={styles.pane}>
              <Rows count={6} rowClass={styles.row72} />
            </div>
            <div className={styles.kernelDetail}>
              <Lines count={5} />
              <Lines count={4} />
            </div>
          </div>
        </div>
      );
    case "aux":
      return (
        <FramedSplit region="aux-workspace" className={styles.auxSplit} panes={["short", "lines"]} />
      );
    case "tools":
      return (
        <FramedSplit region="tools-workspace" className={styles.toolsSplit} panes={["checks", "handle", "lines"]} />
      );
    case "review":
      return (
        <FramedSplit region="review-workspace" className={styles.reviewSplit} panes={["rows", "lines"]} />
      );
    case "evolution":
      return (
        <FramedSplit
          region="evolution-workspace"
          className={styles.evolutionLive}
          panes={["lines", "handle", "lines", "handle", "lines"]}
        />
      );
    case "evolution-runs":
      return (
        <FramedSplit region="evolution-runs" className={styles.evolutionQueue} panes={["rows", "lines"]} />
      );
    case "evolution-library":
      return (
        <FramedSplit region="evolution-library" className={styles.evolutionLibrary} panes={["rows", "lines"]} />
      );
    case "git":
      return (
        <div className={styles.page}>
          <RouteHeaderSlot />
          <div className={styles.gitBody}>
            <div className={styles.gitSummary} />
            <SplitBody
              className={styles.gitWorkspace}
              region="git-workspace"
              panes={["rows", "handle", "lines", "rows"]}
            />
          </div>
        </div>
      );
    case "logs":
      return (
        <FramedSplit
          region="logs-workspace"
          className={styles.logsWorkspace}
          panes={["rows", "handle", "lines", "handle", "lines"]}
        />
      );
    case "memory-browse":
      return <MemoryFrame kind="personal" />;
    case "memory-cards":
      return <MemoryFrame kind="cards" />;
    case "memory-graph":
      return <MemoryFrame kind="graph" />;
    case "memory-knowledge":
      return <MemoryFrame kind="knowledge" />;
    case "memory-ops":
      return <MemoryFrame kind="ops" />;
    case "usage":
      return <UsageFrame />;
    case "pet":
      return <PetFrame />;
    case "reset":
      return <ResetFrame />;
    case "launcher":
      return <LauncherFrame />;
    case "launcher-tools":
      return (
        <div className={styles.page} data-loading-region="launcher-tools-workspace">
          <RouteHeaderSlot />
          <div className={styles.pane}>
            <Rows count={6} rowClass={styles.row44} />
          </div>
        </div>
      );
    case "companions":
      return <CompanionsFrame />;
    default:
      return null;
  }
}
