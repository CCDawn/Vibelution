import styles from "./WorkflowStart.styles";
import { ArrowRight, FileText, GitBranch, LayoutTemplate, Plus, Users } from "lucide-react";
import { VButton } from "../../../components/vui";
import { workflowTemplatePreviews } from "./workflowTemplates";

export function WorkflowStart({ onCreate, onTemplate }: { onCreate: () => void; onTemplate: (id: string) => void }) {
  return <div className={styles.part1}>
    <section className={styles.part2}>
      <div className={styles.part3}><span className={styles.part4}><GitBranch size={21}/></span><h2 className={styles.part5}>从一个流程开始协作</h2></div>
      <p className={styles.part6}>把输入、成员分工和交付结果串起来，下次任务可以直接复用。</p>
      <div className={styles.part7}><h3 className={styles.part8}>选择一个起点</h3><span className={styles.part9}>模板内容均可编辑</span></div>
      <div className={styles.part10}>{workflowTemplatePreviews.map((item,index) => <article key={item.id} className={styles.part11}>
        <div className={styles.part12}><span className={styles.part13}>{index ? <FileText size={18}/> : <LayoutTemplate size={18}/>}</span><span className={styles.part9}>{item.stepCount} 个步骤</span></div>
        <h4 className={styles.part14}>{item.name}</h4><p className={styles.part15}>{item.description}</p>
        <div className={styles.part16}>{item.stepLabels.map((label,i) => <span key={label} className={styles.part17}>{i > 0 && <ArrowRight size={10}/>}<span className={styles.part18} title={label}>{label}</span></span>)}</div>
        <VButton variant={index === 0 ? "primary" : "secondary"} className={styles.part19} trailingIcon={<ArrowRight size={13}/>} onClick={() => onTemplate(item.id)}>使用模板</VButton>
      </article>)}</div>
      <div className={styles.part20}><span className={styles.part21}><Plus size={18}/></span><div className={styles.part22}><h3 className={styles.part23}>从空白开始</h3><p className={styles.part24}>自行定义输入、协作步骤与交付方式。</p></div><VButton className={styles.part25} onClick={onCreate}>创建流程</VButton></div>
      <p className={styles.part26}><Users size={14} className={styles.part27}/>创建后，可从团队成员中为每个步骤分配负责人。</p>
    </section>
  </div>;

}
