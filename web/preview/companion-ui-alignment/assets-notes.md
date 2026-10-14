# 场景预览素材

这些素材使用内置 imagegen 工具生成，保存在本预览目录；不替换正式人物资产。页面将背景与透明人物图分层叠放，没有把聊天控件烘焙进图片。

| 文件 | 场景示例 | 时间 | 地点 | 活动 |
| --- | --- | --- | --- | --- |
| room-background-v1.png | 居家 | 19:30 | 在家 | 自由活动 |
| library-background-v1.png | 学习 | 12:00 | 图书馆 | 复习功课 |
| studio-background-v1.png | 创作 | 15:00 | 创作工作室 | 音乐创作 |
| park-background-v1.png | 散步 | 18:00 | 公园 | 傍晚散步 |
| portrait-cutout-v1.png | 人物透明图 | — | 共用 | 根据原人物图去除背景和光晕 |

以上时间、地点、计划和对话均为预览数据；正式接入时应由人物当前状态选择场景，未来计划不提前改变当前位置。应用关闭后不推进生活。

## 居家背景实际提示词

```text
Use case: illustration-story. Asset type: background-only image for a full-screen anime visual novel companion chat UI. Create a polished wide 16:9 anime bedroom / personal creative studio interior, eye-level camera, soft early-evening daylight through a large window on the left, cool pearl gray and subtle turquoise accents plus warm desk-lamp illumination on the right. A modest desk with music notebooks and small speakers on the left, a tidy comfortable bed and a low shelf on the right, city and gentle sky visible beyond the window. Perspective should feel natural and spacious. Central 40 percent of the frame is open room space with quiet low-detail walls and floor so an existing tall anime character sprite can be placed in the center foreground. Lower quarter should have restrained detail because readable translucent chat will be overlaid. Beautiful painterly anime game background, detailed but calm, crisp without photographic realism. No people, no characters, no silhouettes, no text, no UI, no logos, no watermark. Background fills entire landscape frame, no borders.
```

## 其他三张背景实际提示词

三次调用分别使用以下公共段与各自场景段拼接，transparent_background=false。

公共段：

```text
Create a wide 16:9 anime visual novel background-only illustration for the same companion UI as a calm bedroom with gray-blue walls, cyan accents and softly painted textures. Eye-level camera and natural perspective. Leave the central 40% free of major objects so a tall standing character sprite can be layered there. Lower quarter has quiet detail for translucent chat overlay. No people, no characters, no silhouettes, no readable text, no UI, no logos, no watermarks. Full landscape frame, no borders. High-quality painterly anime game environment, neither photorealistic nor flat vector.
```

图书馆场景段：

```text
 Scene: a bright peaceful public library / campus reading room at midday. Tall windows on the left with green trees outside, oak reading tables and books at the sides, bookshelves in the right background, open quiet aisle in the center foreground. Cool daylight, soft mint accents, peaceful focused atmosphere. Communicate studying and reading rather than bedroom or office.
```

创作场景段：

```text
 Scene: a modest cozy personal music and creative studio in late-afternoon light. Synth keyboard, headphones and open music notebook on desk to the left, monitors and speakers, shelving and a microphone stand toward the right, a small sound-treated wall with tasteful cyan gray acoustic panels. Center foreground is empty standing space. Warm natural left window light with restrained teal accent details. This is a place for making music and creative work, no gaming RGB overload.
```

公园场景段：

```text
 Scene: a tranquil city park walking path at dusk. A broad paved path recedes from empty center foreground, leafy trees at both sides, a bench off to the right, a small pond and city buildings visible distantly on the left. Warm lavender-peach sunset sky, soft evening light matching anime character artwork, subtle cool teal greenery. Peaceful normal daily evening stroll, no fantasy, no dramatic lighting.
```

## 人物去背景实际提示词

输入图：本目录原有 portrait.png；transparent_background=true。原文件保留。

```text
Use case: background-extraction. Edit target: the supplied existing Luo Tianyi character sprite. Remove ALL existing background, ALL gray fog and ALL backdrop glow, including soft shadow/haze between hair ribbons and around the silhouette. Return only the exact existing anime character as a clean cutout on a genuinely transparent alpha background. Preserve character identity and all foreground pixels as closely as possible: same face, green eyes, silver hair with cyan ribbons, same outfit, pose, proportions and framing. Preserve the full existing visible character, including fine hair strands, fingers, clothing details, skirt, and legs. Do not redraw, restyle, beautify, change colors, change facial expression, alter pose or add body parts. No scene, no white fill, no black fill, no shadows outside the character, no lettering. This asset will be layered over an anime bedroom in a browser.
```
