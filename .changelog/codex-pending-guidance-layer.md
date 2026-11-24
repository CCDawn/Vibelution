# 插入消息不再先渲染在活动轮上方

## 现象

运行中的轮次里发送补充消息（guidance）时，这条消息先被拼到对话流里、排在"思考中"
状态之上，等服务端回显落地后再闪一下跳到下面。位置从一开始就是错的。

## 根因

乐观 guidance 行的 metadata 只带 kind/source/guidanceMode/clientSubmissionId/optimistic，
没有 turnId 和 guidanceSequence。conversationGuidanceSegments 的投影要求正整
guidanceSequence 才把这一行当作当前轮的插入行；缺字段时它退化成普通 user 行，
被排在活动轮之前，随后由服务端回显行完成一次真实重排。

## 改动

- `web/src/routes/chat/useChatComposerTurnMutations.ts`：guidance onMutate 从会话缓存解析
  活动轮 turnId（activeTurnId，回退到最后一条 in-flight assistant 行的 turnId），
  乐观行补 turnId 与本地排序位 guidanceSequence；两者都只存在于前端缓存，不写服务端。
- `web/src/components/conversation/conversationGuidanceSegments.test.ts`：新增乐观行归位用例，
  并固定"缺 sequence 会被排到活动轮之前"的旧形状作为回归护栏。

## 验证

- `npx vitest run conversationGuidanceSegments.test.ts ConversationView.test.tsx`：165 用例通过。
- `npx tsc -b`：无类型错误。

## 边界

服务端协议、journal 顺序、稳态渲染管线均未改动；本地排序位不参与任何持久化。
