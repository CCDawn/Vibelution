import { Bot, FolderOpen, ListTodo, ArrowRight } from "lucide-react";
import { VButton } from "../../components/vui";
import styles from "./LauncherAssistantWelcome.styles";
export function LauncherAssistantWelcome({lang,onPrompt}:{lang:"zh"|"en";onPrompt:(text:string)=>void}) {
  const zh=lang === "zh";
  return <section className={styles.root} aria-label={zh ? "开始与助理交流" : "Start a conversation"}>
    <span className={styles.mark}><Bot size={27}/></span><span className={styles.eyebrow}>{zh ? "你的个人助理" : "Your personal assistant"}</span>
    <h2 className={styles.heading}>{zh ? "今天，想一起做点什么？" : "What would you like to work on today?"}</h2>
    <p className={styles.description}>{zh ? "聊一个想法，安排一件事，或从手头的项目开始。" : "Explore an idea, plan a task, or pick up a project."}</p>
    <div className={styles.starters}>
      <VButton variant="ghost" contentLayout="plain" className={styles.starter} onClick={()=>onPrompt(zh ? "帮我梳理今天需要处理的事情。" : "Help me organize today's tasks.")}><ListTodo size={18}/><strong>{zh ? "梳理待办" : "Plan my tasks"}</strong><ArrowRight size={13}/><span className={styles.starterHint}>{zh ? "找到接下来最重要的一件事" : "Find the most important next step"}</span></VButton>
      <VButton variant="ghost" contentLayout="plain" className={styles.starter} onClick={()=>onPrompt(zh ? "帮我看看已连接项目的当前进展。" : "Show me the progress of the connected project.")}><FolderOpen size={18}/><strong>{zh ? "了解项目" : "Review a project"}</strong><ArrowRight size={13}/><span className={styles.starterHint}>{zh ? "看看进展，再决定下一步" : "Review progress and choose what comes next"}</span></VButton>
    </div>
  </section>;
}
