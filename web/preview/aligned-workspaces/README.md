# Skill 与记忆工作台验收

直接渲染正式 SkillsRoute、MemoryRoute 和公共 VUI recipes，包含 Skill、个人记忆、团队记忆、整个记忆库、图谱、知识治理、管理和清理。数据全部由 fixtures.ts 的确定性安全样例提供，不含真实配置、私有记忆或控制凭据。

从 web 运行 `node node_modules/vite/bin/vite.js --config preview/aligned-workspaces/vite.config.ts`，打开 `/preview/aligned-workspaces/index.html?page=skills`。顶部为验收页选择器；页面内部仍保留原生导航与功能。

仅已声明 GET 返回样例；所有写请求及未知请求返回 403，后台 proxy 为空，不执行真实导入、保存、删除、工具或模型调用。截图只能证明这些正式组件在样例下的表现，不能证明正式实例已加载新版，或真实写操作已完成。
