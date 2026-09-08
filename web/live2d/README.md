# Desktop pet Live2D adapter

The selected character is XiaoLuo (小洛), created by 火爆鸡王, depicting
Luo Tianyi (上海禾念). The user explicitly confirmed obtaining permission.
This is local integration; no remote publication or release is authorized.

Source: https://github.com/HuxiaoRoar/NewLuotianyi-Live2D
Pinned model revision: 083b6e21cb8228febb11e87f72d367529ba033b7
Source directory: live2d/model/小洛
Original author: https://www.bilibili.com/video/BV1Bk88eDEoK

The upstream GPLv2 does not license the model assets or Live2D SDK.
Preserve their separate ownership. Confirm the applicable permissions and SDK
publication requirements before distributing a release.

The official Cubism Web SDK 5-r.5 Framework and Core are reused directly.
No PixiJS, Three.js, voice engine, or second Agent stack is introduced.
The adapter uses separate compilation for the Framework's legacy class fields;
application TypeScript strictness is unchanged.

Rebuild with the already accepted SDK and authorized model directory:

    node web/scripts/buildDesktopPetLive2d.mjs <SDK directory> <XiaoLuo directory>

Normal builds use the bounded local output and never download a model or CDN
script. The six original silent motion files are retained; the production
completion state currently uses the head motion. Other activity states use
model parameters, including the question-mark and happiness parameters.
They are not nine newly authored motion files.

The existing /api/pet/activity projection remains the sole state source.
No ordinary Session code changes. Drag threshold, HUD, close and tray reopening
remain in their existing owners. Loading/failure states are explicit.
Reduced motion freezes animation; hidden pages suspend rendering.
The original 2D PNG is retained as an asset, but is not silently substituted
for a failed Live2D load. Model importing is not included in this integration.
