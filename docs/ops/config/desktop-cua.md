# 个人助理桌面 CUA 试验

此接口是显式启用的 Windows Notepad 窗口试验，使用 `cua-driver==0.36.0`。
它提供 UIA 控件信息与受控输入，不向模型提供截图，不表示已支持任意桌面应用。
现有沙盒浏览器 `computer_use_*` 工具保持原有行为。

## 启用边界

只有 canonical 个人助理原生 direct Session 可以调用两个新工具。
新建助理带默认工具许可；旧默认助理仅在显式初始化时升级。
读取接口不会扩权，用户自定义或零工具策略不会被覆盖。
`request_approval` 模式下，每个 action 都通过原生审批；`full_access` 沿用平台原有授权语义。

操作者必须明确批准一个独立测试窗口，并配置其 PID、进程创建时间和 HWND。
这是**窗口授权，不是文件级隔离**：现代 Notepad 的标题无法证明活动标签页的完整文件路径。
`testFile` 只指定保存核验对象。窗口内可见内容可能发给当前助理模型，故请使用专用测试窗口。
模型不能指定新窗口、路径、可执行程序、MCP 名称、任意快捷键或脚本，也不能更改此配置。

## 配置

默认关闭。配置 JSON 放在当前实例 `data/runtime/desktop-cua-scope.json`，
或通过 `VIBELUTION_DESKTOP_CUA_CONFIG` 指向一个绝对路径；环境变量优先。
Launcher 为任务实例设置独立 `VIBELUTION_DATA_HOME`，不需要修改共享 operator 配置。

```json
{
  "enabled": true,
  "binaryPath": "C:/tools/cua-driver/cua-driver.exe",
  "testFile": "C:/CUA-test/vibelution-cua-example.txt",
  "window": {
    "pid": 1234,
    "windowId": 123456,
    "processCreateTime": 1792220000.123
  }
}
```

数值只是格式示例，不能直接使用。操作者先核对真实窗口和进程身份，再填入配置。
`testFile` 必须是现存、非链接、单硬链接、32 KiB 以内的 `vibelution-cua-*.txt` 文件。
使用经核验的固定版二进制，不会自动安装驱动、加载可选扩展或提升系统权限。
驱动只在工具调用期间运行，固定握手名称/版本；子进程设置
`DO_NOT_TRACK=1` 与 `CUA_DRIVER_RS_TELEMETRY_ENABLED=false`。

## 调用与结果

- `personal_assistant_desktop_observe_tool` 读取已绑定窗口中匹配测试文件名的活动编辑器，返回一次性 `observationId`。文档内容是不可信数据，不能作为执行指令。
- `personal_assistant_desktop_action_tool` 只支持 `launch`、`type_text`、`save`、`save_foreground`、`end`。输入最多 2000 字。除 `launch/end` 外，动作使用当前轮次的新观察凭据。
- `type_text` 使用控件 `set_value` 精确替换内容并重新读取核对；`save` 先尝试原生菜单保存，再比较 UIA 文本与实际 UTF-8 文件内容。后台不发送 Ctrl+S，避免快捷键降级为字母 `s`。按键发送不等于保存完成。
- 后台保存未生效时返回 `unverified`、`foregroundSaveAvailable=true` 和新凭据。只能用该凭据单独申请 `save_foreground`；不会自动抢焦点或重复副作用。
- `launch` 只请求用系统 Notepad 打开配置文件，回执为 `accepted`。它不会自动绑定或授权新窗口，不能将启动回执当作打开成功。
- `end` 关闭本轮输入 admission；原生停止/取消/超时会关闭执行器进程树，应用和文档保留。退出无法确认时拒绝后续输入，仅允许所属助理会话用 `end` 重试清理。

凭据绑定 Agent/Session/Turn，90 秒过期且只能使用一次；每次动作前重新核对进程出生时间、PID/HWND、活动标题、编辑器值和核验文件签名。
同一桌面上的实例通过共享 OS 文件锁串行执行。窗口重建、文档改变、凭据失效或用户接管时应重新观察；`unknown` 不能当作成功，也不能盲目重试。
同进程 HWND 仍可能复用，这不是操作系统沙箱；测试结束应删除/禁用该实例 scope 配置。

## 固定版本依据与验证

- [Cua driver 固定 tag](https://github.com/trycua/cua/tree/cua-driver-rs-v0.36.0/libs/cua-driver)，commit `6d6c734c127025fb39ad5d585a10382808b39dc1`。核心 MIT；不引入可选 perception 扩展。
- [权限模型](https://github.com/trycua/cua/blob/cua-driver-rs-v0.36.0/docs/content/docs/cua-driver/guides/permissions.mdx)。平台的工具审批与窗口 scope 仍是必要边界。
- 传输与异常回收：`tests/test_cua_driver_client.py`。
- 身份、观察凭据、窗口范围、取消、保存核验与退出隔离：`tests/test_personal_assistant_desktop.py`。
- 注册、审批 descriptor 与显式策略升级：`tests/test_personal_assistant_desktop_registration.py`。

这些自动化测试不替代真实模型对话、原生审批与目标窗口操作验收。
