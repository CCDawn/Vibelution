import { groupConsecutiveBy, shouldCollapseGroupMessage } from "../routes/chat/chatRoutePresentation";

export type StreamAudience = "user" | "internal";
export type StreamVisibility = "default" | "collapsed_by_default";
export type PreviewSceneId = "discuss" | "consecutive" | "summary";

export type PreviewProcess = {
  summary: string;
  detail: string;
  settled: boolean;
};

export type PreviewMessage = {
  id: string;
  speakerId: string;
  speakerName: string;
  speakerRole: string;
  initials: string;
  time: string;
  body: string;
  audience: StreamAudience;
  visibility: StreamVisibility;
  process?: PreviewProcess;
  pending?: boolean;
};

export type PreviewDigest = {
  title: string;
  points: string[];
};

export type PreviewRound = {
  title: string;
  mode: string;
  status: string;
  topic: string;
  topicAuthor: string;
  messages: PreviewMessage[];
  digest?: PreviewDigest;
};

export const STREAM_CLAMP_LINES = 8;

export function shouldClampStreamBody(content: string) {
  return shouldCollapseGroupMessage(content);
}

export function groupConsecutiveSpeakers<T extends { speakerId: string }>(messages: readonly T[]): T[][] {
  return groupConsecutiveBy(messages, (message) => message.speakerId);
}

export const LONG_INTERNAL_DISCUSSION =
  "先看主诉：妊娠28周，反复头晕两天，血压在诊所测到 148/96。"
  + "既往有轻度贫血，没有子痫前期诊断。我倾向先把这轮当成需要鉴别的血压升高，而不是直接下结论。"
  + "检查单里尿蛋白还没回，血红蛋白 98，胎心目前稳定。"
  + "建议这一轮把危险信号清单摊开，再决定要不要立刻转急诊。"
  + "对用户侧先不要说确诊，只说明还在交叉核对体征和化验。"
  + "如果蛋白尿阳性或出现视物模糊、上腹痛，再升级处理路径。"
  + "讨论可以写长一些，但房间时间线必须仍能直接读到这段开头，而不是只剩一张空卡片。"
  + "把鉴别要点、待回化验和对外口径分开写，避免合成阶段再从折叠卡片里翻原文。"
  + "这一段故意写过现网 260 字阈值，用来对照：左边会整段藏掉，右边应仍能扫到开头。";

export const LONG_INTERNAL_COUNTER =
  "同意先不当成确诊。我补一条：头晕也可能是贫血叠加体位，不能只盯血压。"
  + "当前血红蛋白 98 已经够解释一部分症状，但 148/96 仍然值得并列跟踪。"
  + "这一轮我建议输出三件事：继续监测血压、等尿蛋白、告诉用户哪些危险信号要立刻就诊。"
  + "合成阶段再把这些收成一段对用户可说的话，讨论过程本身不必对外展开。"
  + "如果下一轮蛋白尿仍阴性且症状缓解，可以降级成常规产检随访，而不是继续按急症口径说话。"
  + "操作员打开群聊时，这段反驳也应默认可见，折叠只留给思考过程和超长正文的后半段。"
  + "连续发言也不要再套描边行，头像和名字只在说话人切换时出现一次。"
  + "这一段同样超过 260 字，用来确认建议列是截断而不是 hidden。";

export const PREVIEW_SCENES: Record<PreviewSceneId, PreviewRound> = {
  discuss: {
    title: "产科会诊 · 第 1 轮",
    mode: "discuss",
    status: "进行中",
    topic: "28 周孕妇头晕两天，诊所血压 148/96，先怎么看？",
    topicAuthor: "你",
    messages: [
      {
        id: "m-planner",
        speakerId: "agent-planner",
        speakerName: "顾言初",
        speakerRole: "planner",
        initials: "顾",
        time: "12:41",
        body: LONG_INTERNAL_DISCUSSION,
        audience: "internal",
        visibility: "collapsed_by_default",
        process: {
          summary: "已处理 2 个工具",
          detail: "read 产检摘要 · search 子痫前期危险信号",
          settled: true,
        },
      },
      {
        id: "m-reviewer",
        speakerId: "agent-reviewer",
        speakerName: "白望舒",
        speakerRole: "reviewer",
        initials: "白",
        time: "12:42",
        body: LONG_INTERNAL_COUNTER,
        audience: "internal",
        visibility: "collapsed_by_default",
      },
      {
        id: "m-pending",
        speakerId: "agent-clinician",
        speakerName: "沈照晚",
        speakerRole: "clinician",
        initials: "沈",
        time: "12:42",
        body: "",
        audience: "internal",
        visibility: "collapsed_by_default",
        pending: true,
      },
    ],
  },
  consecutive: {
    title: "产科会诊 · 第 1 轮",
    mode: "discuss",
    status: "进行中",
    topic: "先把监测项拆开，不要一次抛整段方案。",
    topicAuthor: "你",
    messages: [
      {
        id: "c1",
        speakerId: "agent-planner",
        speakerName: "顾言初",
        speakerRole: "planner",
        initials: "顾",
        time: "12:44",
        body: "先记血压，4 小时内再测一次。",
        audience: "user",
        visibility: "default",
      },
      {
        id: "c2",
        speakerId: "agent-planner",
        speakerName: "顾言初",
        speakerRole: "planner",
        initials: "顾",
        time: "12:44",
        body: "尿蛋白没回之前，不对用户说确诊。",
        audience: "user",
        visibility: "default",
      },
      {
        id: "c3",
        speakerId: "agent-planner",
        speakerName: "顾言初",
        speakerRole: "planner",
        initials: "顾",
        time: "12:45",
        body: "危险信号只保留视物模糊、上腹痛、头痛加重。",
        audience: "user",
        visibility: "default",
      },
      {
        id: "c4",
        speakerId: "agent-reviewer",
        speakerName: "白望舒",
        speakerRole: "reviewer",
        initials: "白",
        time: "12:45",
        body: "同意。贫血那句放到随访建议里，不要和急症信号混在一起。",
        audience: "user",
        visibility: "default",
      },
    ],
  },
  summary: {
    title: "产科会诊 · 第 1 轮",
    mode: "synthesize",
    status: "已结束",
    topic: "把这一轮收成对用户可说的话。",
    topicAuthor: "你",
    messages: [
      {
        id: "s1",
        speakerId: "agent-planner",
        speakerName: "顾言初",
        speakerRole: "planner",
        initials: "顾",
        time: "12:50",
        body: "对外口径：血压偏高需要复查，还不是确诊；先监测，等待化验。",
        audience: "user",
        visibility: "default",
      },
      {
        id: "s2",
        speakerId: "agent-reviewer",
        speakerName: "白望舒",
        speakerRole: "reviewer",
        initials: "白",
        time: "12:51",
        body: "补充危险信号三句，并明确血红蛋白偏低只解释部分头晕。",
        audience: "user",
        visibility: "default",
      },
    ],
    digest: {
      title: "本轮纪要",
      points: [
        "结论：血压升高待查，不按子痫前期对外表述。",
        "下一步：复查血压、等尿蛋白、告知三条危险信号。",
        "用户可见：短建议；内部讨论留在房间时间线里。",
      ],
    },
  },
};

export const PREVIEW_SCENE_ORDER: Array<{ id: PreviewSceneId; label: string }> = [
  { id: "discuss", label: "内部长讨论" },
  { id: "consecutive", label: "连续同说话人" },
  { id: "summary", label: "轮次摘要" },
];
