import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ArrowRight, Check, ChevronDown, CirclePause, Play, RotateCcw, ShieldCheck, Square, Workflow } from "lucide-react";
import { VButton, VChip, VDenseOpsPage, VNativeInput, VNativeSelect, VSwitch, VuiProvider } from "../components/vui";
import "./base.css";
import "./tokens.css";
import "./vui-native-controls.css";
import "./vui-provider-theme.css";
import "./harness-supervision-preview.css";

type RunStatus = "ready" | "running" | "recovering" | "director" | "user" | "stopped" | "complete";
type Run = { status: RunStatus; rounds: number; minutes: number; failures: number; message: string; events: string[] };
const initialRun: Run = { status: "ready", rounds: 0, minutes: 0, failures: 0, message: "配置就绪，等待开始", events: [] };
const roleDefinitions = [
  { id: "assistant", name: "个人助理", summary: "接收目标 · 汇总进展", initial: "个人助理", choices: ["个人助理", "任务协调助理"] },
  { id: "director", name: "总监", summary: "异常裁决 · 监督续跑", initial: "平台总监", choices: ["平台总监", "工程总监"] },
  { id: "developer", name: "开发", summary: "按授权范围实施", initial: "平台开发", choices: ["平台开发", "代码开发"] },
  { id: "reviewer", name: "审查", summary: "独立检查 · 验证结果", initial: "代码审查", choices: ["代码审查", "质量审查"] },
];
const labels: Record<RunStatus, string> = { ready: "待运行", running: "运行中", recovering: "安全恢复中", director: "等待总监", user: "等待用户", stopped: "已停止", complete: "已完成" };
const phases = ["开发实施", "独立审查", "验证结果"];
const authorizedMinutes = 30;

function HarnessSupervisionPreview() {
  const [enabled, setEnabled] = useState(true);
  const [roundLimit, setRoundLimit] = useState("3");
  const [timeLimit, setTimeLimit] = useState("30");
  const [bindings, setBindings] = useState(() => Object.fromEntries(roleDefinitions.map((role) => [role.id, role.initial])));
  const [details, setDetails] = useState(false);
  const [run, setRun] = useState<Run>(initialRun);
  const roundBudget = Number(roundLimit);
  const minuteBudget = Math.min(Number(timeLimit), authorizedMinutes);
  const valid = Number.isInteger(roundBudget) && roundBudget >= 1 && roundBudget <= 10 && Number.isInteger(Number(timeLimit)) && Number(timeLimit) >= 1 && Number(timeLimit) <= 60;
  const active = ["running", "recovering", "director", "user"].includes(run.status);
  const event = (current: Run, message: string): string[] => [message, ...current.events].slice(0, 6);

  // Deterministic local simulation only: one real second represents one minute.
  // Neither role bindings nor run controls issue requests or persist state.
  useEffect(() => {
    if (run.status !== "running") return;
    const timer = window.setInterval(() => {
      setRun((current) => {
        if (current.status !== "running") return current;
        const minutes = current.minutes + 1;
        const roundDone = minutes % 3 === 0;
        const rounds = current.rounds + Number(roundDone);
        const exhausted = minutes >= minuteBudget || rounds >= roundBudget;
        const message = exhausted
          ? rounds >= roundBudget ? "已达到轮数上限，结果已保留" : "已达到有效时限，结果已保留"
          : roundDone ? `第 ${rounds} 轮成功，继续下一轮` : phases[minutes % 3];
        return { ...current, minutes, rounds, failures: roundDone ? 0 : current.failures, status: exhausted ? "complete" : "running", message, events: roundDone || exhausted ? event(current, message) : current.events };
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [run.status, roundBudget, minuteBudget]);

  useEffect(() => {
    if (run.status !== "recovering") return;
    const timer = window.setTimeout(() => setRun((current) => {
      if (current.status !== "recovering") return current;
      const message = "检查点与授权均有效，已自动安全续跑";
      return { ...current, status: "running", message, events: event(current, message) };
    }), 1800);
    return () => window.clearTimeout(timer);
  }, [run.status]);

  function start() {
    if (!enabled || !valid) return;
    setRun({ ...initialRun, status: "running", message: "第 1 轮 · 开发实施", events: ["个人助理确认目标与范围，总监开始监督"] });
  }
  function simulate(kind: "failure" | "exhausted" | "safe" | "unknown") {
    setRun((current) => {
      if (current.status !== "running") return current;
      if (kind === "safe") {
        const message = "发现安全中断，正在校验检查点与剩余授权";
        return { ...current, status: "recovering", message, events: event(current, message) };
      }
      if (kind === "unknown") {
        const message = "操作副作用不明，已暂停并交总监裁决";
        return { ...current, status: "director", message, events: event(current, message) };
      }
      const failures = current.failures + 1;
      const escalate = kind === "exhausted" || failures >= 3;
      const message = kind === "exhausted" ? "现有重试已耗尽，已升级总监" : escalate ? "连续 3 次失败，已升级总监" : `连续失败 ${failures}/3 · 沿用现有重试策略`;
      return { ...current, failures, status: escalate ? "director" : "running", message, events: event(current, message) };
    });
  }
  function stop() {
    setRun((current) => ({ ...current, status: "stopped", message: "已停止，不再启动下一步；已有结果已保留", events: event(current, "用户停止本次运行") }));
  }
  const tone = run.status === "director" || run.status === "user" ? "warning" : run.status === "complete" ? "success" : run.status === "running" || run.status === "recovering" ? "info" : "neutral";

  return (
    <div className="hsp-root">
      <header className="hsp-topbar">
        <span className="hsp-brand"><span className="hsp-brand-mark">V</span> Vibelution</span>
        <span className="hsp-breadcrumb">平台 <ArrowRight size={12} /> 自进化</span>
        <VChip tone="neutral">交互预览</VChip>
      </header>
      <main className="hsp-workspace">
        <VDenseOpsPage ariaLabel="自进化监督配置" fill={false} className="hsp-page" title="自进化监督" meta="在授权内持续改进，异常时有人接手" headerClassName="hsp-page-header" actions={<span className="hsp-local"><span /> 仅本地模拟</span>}>
          <div className="hsp-content">
            <section className="hsp-enable" aria-label="启用配置">
              <span className="hsp-enable-icon"><Workflow size={22} /></span>
              <div className="hsp-enable-copy"><h2>让团队继续完成下一轮</h2><p>成功后继续，达到轮数或有效时限即停止。</p></div>
              <div className="hsp-switch"><span>{enabled ? "已启用" : "已关闭"}</span><VSwitch aria-label="启用自进化监督" isSelected={enabled} isDisabled={active} onChange={setEnabled} /></div>
            </section>

            <section className="hsp-section" aria-labelledby="hsp-roles">
              <div className="hsp-section-title"><h2 id="hsp-roles">角色分工</h2><span>用户保留授权与部署决定权</span></div>
              <div className="hsp-human"><span className="hsp-avatar hsp-avatar-human">你</span><strong>用户</strong><span>确定目标、文件范围与授权期限</span><VChip>最终决定</VChip></div>
              <div className="hsp-role-grid">
                {roleDefinitions.map((role, index) => <div className="hsp-role" key={role.id}>
                  <div className="hsp-role-title"><span className={`hsp-avatar hsp-avatar-${index}`}>{role.name.slice(0, 1)}</span><label htmlFor={`hsp-${role.id}`}>{role.name}</label>{index < 3 && <ArrowRight className="hsp-flow-arrow" size={13} />}</div>
                  <VNativeSelect id={`hsp-${role.id}`} aria-label={`${role.name}绑定`} value={bindings[role.id]} disabled={active || !enabled} onChange={(e) => setBindings({ ...bindings, [role.id]: e.target.value })}>{role.choices.map((choice) => <option key={choice}>{choice}</option>)}</VNativeSelect>
                  <p>{role.summary}</p>
                </div>)}
              </div>
            </section>

            <section className="hsp-section hsp-budget-section" aria-labelledby="hsp-budget">
              <div className="hsp-section-title"><h2 id="hsp-budget">运行预算</h2><span>任一上限先到即停止</span></div>
              <div className="hsp-budget">
                <label className="hsp-number"><span>最多轮数</span><div><VNativeInput type="number" min={1} max={10} step={1} aria-label="最多轮数" value={roundLimit} disabled={active || !enabled} onChange={(e) => setRoundLimit(e.target.value)} /><span>轮</span></div><small>1–10 轮</small></label>
                <label className="hsp-number"><span>总时限</span><div><VNativeInput type="number" min={1} max={60} step={1} aria-label="总时限" value={timeLimit} disabled={active || !enabled} onChange={(e) => setTimeLimit(e.target.value)} /><span>分钟</span></div><small>1–60 分钟</small></label>
                <div className="hsp-authorization"><ShieldCheck size={18} /><div><strong>本次授权剩余 30 分钟</strong><p>有效时限 {valid ? minuteBudget : "—"} 分钟，以更早到期的授权为准。</p></div></div>
              </div>
              {!valid && <p className="hsp-error" role="alert">轮数请输入 1–10 的整数，时限请输入 1–60 的整数。</p>}
              <div className="hsp-scope"><span>固定文件范围</span><code>core/orchestration/harness_campaign.py</code><code>tests/test_harness_campaign.py</code><span className="hsp-scope-note">模拟授权 · 各轮保持一致</span></div>
            </section>

            <section className="hsp-run" aria-labelledby="hsp-status-title" data-status={run.status}>
              <div className="hsp-run-heading"><h2 id="hsp-status-title">运行状态</h2><VChip tone={tone}>{labels[run.status]}</VChip><div className="hsp-run-actions">{active ? <VButton icon={<Square size={13} />} onPress={stop}>停止</VButton> : <VButton variant="primary" icon={run.status === "ready" ? <Play size={14} /> : <RotateCcw size={14} />} isDisabled={!enabled || !valid} onPress={start}>{run.status === "ready" ? "开始模拟" : "重新模拟"}</VButton>}</div></div>
              <div className="hsp-status-copy" role="status" aria-live="polite"><span className={`hsp-status-dot hsp-status-${run.status}`} /><strong>{run.message}</strong></div>
              <div className="hsp-progress-line"><span>已完成 <b>{run.rounds}</b> / {valid ? roundBudget : "—"} 轮</span><span>已用 <b>{run.minutes}</b> / {valid ? minuteBudget : "—"} 分钟</span><span>连续失败 <b>{run.failures}</b> / 3</span></div>
              <div className="hsp-progress" aria-hidden="true"><span style={{ width: `${valid ? Math.min(100, Math.max(run.rounds / roundBudget, run.minutes / minuteBudget) * 100) : 0}%` }} /></div>
              {run.status === "director" && <div className="hsp-decision"><CirclePause size={17} /><div><strong>{bindings.director}正在接手</strong><p>先核对副作用与授权；范围或权限需要改变时，再交用户确认。</p></div><VButton onPress={() => setRun((current) => ({ ...current, status: "user", message: "总监建议调整范围，等待用户重新授权", events: event(current, "总监请求用户重新授权；未扩大范围") }))}>模拟需用户决定</VButton></div>}
              {run.status === "user" && <p className="hsp-waiting">用户尚未授权，团队保持暂停。部署也始终等待用户决定。</p>}
              <div className="hsp-simulator"><span>模拟事件</span><VButton variant="ghost" isDisabled={run.status !== "running"} onPress={() => simulate("failure")}>失败一次</VButton><VButton variant="ghost" isDisabled={run.status !== "running"} onPress={() => simulate("exhausted")}>重试耗尽</VButton><VButton variant="ghost" isDisabled={run.status !== "running"} onPress={() => simulate("safe")}>安全中断</VButton><VButton variant="ghost" isDisabled={run.status !== "running"} onPress={() => simulate("unknown")}>副作用不明</VButton></div>
            </section>

            <section className="hsp-details">
              <VButton variant="ghost" contentLayout="plain" className="hsp-details-toggle" aria-expanded={details} aria-controls="hsp-detail-body" trailingIcon={<ChevronDown className={details ? "hsp-chevron-open" : ""} size={16} />} onPress={() => setDetails(!details)}><span>监督规则与运行记录</span><span className="hsp-details-subtitle">失败升级 · 安全续跑 · 授权边界</span></VButton>
              {details && <div id="hsp-detail-body" className="hsp-detail-body"><div className="hsp-rules"><p><Check size={14} /><span><strong>失败升级</strong>现有重试耗尽或连续 3 次失败，任一触发即交总监。</span></p><p><Check size={14} /><span><strong>安全续跑</strong>检查点、文件范围、授权均有效，且确认无未知副作用时自动恢复。</span></p><p><Check size={14} /><span><strong>暂停裁决</strong>副作用不明交总监；扩范围、加权限、授权过期交用户，不自动部署。</span></p></div><div className="hsp-log"><h3>本次模拟记录</h3>{run.events.length ? <ol>{run.events.map((entry, index) => <li key={`${index}-${entry}`}><span>{String(run.events.length - index).padStart(2, "0")}</span>{entry}</li>)}</ol> : <p>开始模拟后，在这里查看关键节点。</p>}</div></div>}
            </section>
            <footer className="hsp-footer">所有数据均为模拟 · 1 秒代表 1 分钟 · 不连接真实任务或写接口</footer>
          </div>
        </VDenseOpsPage>
      </main>
    </div>
  );
}

const previewRoot = createRoot(document.getElementById("root")!);
previewRoot.render(<VuiProvider><HarnessSupervisionPreview /></VuiProvider>);
if (import.meta.hot) import.meta.hot.dispose(() => previewRoot.unmount());
