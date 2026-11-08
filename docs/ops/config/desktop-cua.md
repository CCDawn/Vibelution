# 个人助理桌面 CUA

## 电脑操作模型

个人助理右栏的“电脑操作”面板与 Launcher 会话内嵌的操作卡片共享同一套原生电脑
工具。当前模型下，助理**无需预先授权**即可对桌面执行观察与操作：observe/action
不再要求授权回执，`authorization_required` 回执与授权请求卡不再出现，每步一次性
确认卡也已取消，改为事件审计留痕（观察、动作、窗口切换、应用启动）。

- **窗口自选**：工具提供可选 `window` 参数，模型可自行选择要观察或操作的目标
  窗口；observe 回执中的窗口候选列表（`candidates`）仅供模型决策，壳侧对未知
  窗口标识不做硬拒。
- **启动应用**：动作集包含 `launch`，语义为 `os.startfile`（ShellExecute 打开），
  不经过可见控制台，不弹出终端窗口；动作集还可能包含 `click_at`、`hotkey` 等
  新动作，壳侧校验保持宽松透传，由核心裁决。
- **默认目标偏好**：操作栏中的“授权此窗口”退化为可选偏好——为当前会话设置
  默认操作窗口，不再是操作前置条件；未设置时助理自行选窗。`grant`/`confirm`
  HTTP 接口保留，仅用于设置该偏好与历史确认兼容。
- **暂停与接管**：操作栏的暂停/继续/接管/交回按钮不变，状态轮询保持只读投影。

授权仍绑定 PID、HWND、进程创建时间、可执行文件与助理配置版本，20 分钟后结束。
关闭窗口、替换进程或改变助理模型/权限配置均需重设默认目标。暂停或人工接管使
全部旧观察失效，交回后重新观察。

以下边界不随本次放开变化：

- **敏感进程过滤**：系统安全与提权界面等敏感窗口仍被排除在可操作集合外。
- **人工接管暂停**：操作者随时可以暂停或接管；检测到真人鼠标/键盘输入时自动交还。
- **跨实例锁**：同一桌面上的多个实例通过共享 OS 锁串行执行电脑动作。
- **quarantine**：不可信内容进入会话前的隔离语义不变，电脑动作不读取或执行隔离
  区内容。
- **传输门**：电脑控制 HTTP 仅允许具有本机控制 token 的特权操作者，拒绝 Agent
  来源会话，且仅接受 localhost 来源；bearer 转发与 Electron 主进程校验镜像不变。

默认助理使用 `networkAccess=restricted`，允许白名单内的截图理解调用；它不会因此
获得网页浏览或任意网络工具。用户明确改为 `none` 时保持该限制，默认目标偏好不能
覆盖工具网络策略。

## 旧记事本试验接口

此接口是显式启用的 Windows Notepad 窗口试验，使用 `cua-driver==0.36.0`。
它提供 UIA 控件信息与受控输入，不向模型提供截图，不表示已支持任意桌面应用。
现有沙盒浏览器 `computer_use_*` 工具保持原有行为。

## 驱动与配置

仍使用已安装的 `cua-driver 0.36.0`，不自动安装或提权。驱动路径可设置为
`VIBELUTION_COMPUTER_CUA_DRIVER`，或在本实例 `data/runtime/computer-cua-driver.json`
中配置 `{"binaryPath":"C:/tools/cua-driver/cua-driver.exe"}`。也兼容从旧试验配置
读取驱动路径。Launcher 助理没有显式驱动配置时，还会查找已安装的
`%LOCALAPPDATA%/Vibelution/Tools/cua-driver/0.36.0/cua-driver.exe`；普通项目不
使用此回退。路径可读仅表示候选存在，实际调用时仍需通过固定版本的 MCP 握手。

电脑操作的实例级配置 JSON 放在当前实例 `data/runtime/desktop-cua-scope.json`，
或通过 `VIBELUTION_DESKTOP_CUA_CONFIG` 指向一个绝对路径；环境变量优先。
Launcher 为任务实例设置独立 `VIBELUTION_DATA_HOME`，不需要修改共享 operator 配置。

```json
{
  "enabled": true,
  "binaryPath": "C:/tools/cua-driver/cua-driver.exe"
}
```

数值只是格式示例。使用经核验的固定版二进制，不会自动安装驱动、加载可选扩展或
提升系统权限。驱动只在工具调用期间运行，固定握手名称/版本；子进程设置
`DO_NOT_TRACK=1` 与 `CUA_DRIVER_RS_TELEMETRY_ENABLED=false`。

## 固定版本依据与验证

- [Cua driver 固定 tag](https://github.com/trycua/cua/tree/cua-driver-rs-v0.36.0/libs/cua-driver)，commit `6d6c734c127025fb39ad5d585a10382808b39dc1`。核心 MIT；不引入可选 perception 扩展。
- [权限模型](https://github.com/trycua/cua/blob/cua-driver-rs-v0.36.0/docs/content/docs/cua-driver/guides/permissions.mdx)。敏感进程过滤与传输门仍是必要边界。
- 传输与异常回收：`tests/test_cua_driver_client.py`。
- 身份、观察凭据、窗口范围、取消与退出隔离：`tests/test_personal_assistant_desktop.py`。
- 注册、动作 descriptor 与策略升级：`tests/test_personal_assistant_desktop_registration.py`。

这些自动化测试不替代真实模型对话与目标窗口操作验收。
