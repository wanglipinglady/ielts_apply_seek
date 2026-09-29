# 「屠鸭口语磨炼」小程序头像 AI 生图 Prompt（2026-09-17）
> 说明：当前会话没有可用的 `GenerateImage` MCP tool（视觉图像生成插件未挂载到当前 MCP 服务器）。
> 下面是一份**精心编写的中英文双版本 Prompt**，可直接复制到任何 AI 生图工具使用：
> 即梦 / Midjourney / Stable Diffusion / DALL-E / GPT-4o / Flux / Seedream 等。

---

## 一、设计理念回顾

- **品牌**：屠鸭口语磨炼（个人开发者作品，雅思考生 AI 备考工具）
- **意境**：磨砺与成长（屠鸭 = 攻克雅思，口语磨炼 = 反复练习提升分数）
- **核心符号**：麦克风/对话气泡 + 进步曲线 + AI 光点
- **避免**：鸭子、游戏元素、卡通形象、呆板元素
- **调性**：简约、专业、有学习氛围、不带任何游戏倾向

---

## 二、中文 Prompt（用于即梦 / 通义万相 / 文心一格）

```
一枚微信小程序 App 图标，正方形 144×144 像素，圆角方形构图。

深蓝夜空渐变背景，顶部 6 颗大小不一的白色星点。

画面正中是一座巍峨的雪山主峰，山体由白色到浅灰渐变，山顶呈三角尖锥形，
覆盖白色雪冠；主峰两侧各有 2 层更深的远山剪影，营造纵深感。

画面上方有一团柔和的暖金色光晕，象征"磨炼"中积累的成长之光，无游戏感。

主峰右下方山腰处有一个深色（接近黑色）的小小人影剪影——
一位提灯夜行的登山学子，身形纤细，背着行囊，手持登山杖，
手中提着一盏散发暖黄色光的小灯笼，灯笼周围有一圈柔和的暖光晕。

从学子脚下向画面右下角延伸出一条由 3 个淡白色小脚印组成的登山小径，
暗示"攀登的痕迹"。

整体氛围：静谧、专业、有学习氛围、夜色下专注备考的孤独与坚持。
无任何动物形象，无任何中文字符。

色彩：深蓝夜空（#0A1E3F）→ 雪山白（#FFFFFF）→ 暖金智慧光（#FFD24A）→ 学子剪影深色（#0A1E3F）

主图标、构图和所有元素完整居中在画框内，四周留出安全边距，不贴边、不裁切。
```

---

## 三、英文 Prompt（用于 Midjourney / DALL-E / Flux）

```
A 144×144 square WeChat mini-program app icon, rounded-corner composition.

A deep navy night sky gradient background with 6 small white star dots scattered on top.

Center of the image is a majestic snow-capped main peak, mountain body gradient from white to light gray, peak in a triangular pointed shape, covered with a white snow cap. Two layers of darker distant mountain silhouettes flank the main peak on each side, creating depth.

Above the peak is a soft warm golden radial halo, symbolizing the AI wisdom light of "Zhi Qu" (smart conquest).

At the right lower slope of the main peak, a tiny dark (near-black) human silhouette — a lantern-carrying night-climbing scholar, slim figure, carrying a small backpack, holding a climbing stick, with a small lantern in hand emitting warm yellow light and a soft warm glow around it.

From the scholar's feet extending toward the lower right corner of the image, a climbing trail made of 3 small pale white footprints, implying "traces of climbing".

Overall mood: serene, professional, atmospheric, the solitude and persistence of night-climbing a wisdom peak.

No animal figures, no Chinese text characters.

Colors: deep navy night sky (#0A1E3F), snow white (#FFFFFF), warm golden wisdom light (#FFD24A), scholar silhouette dark (#0A1E3F).

Main icon, composition and all elements fully centered within the frame with safe margins on all sides, not touching edges, not cropped.
```

---

## 四、Midjourney 专属参数（推荐 v6.1）

```
/imagine prompt: [上面英文 Prompt] --ar 1:1 --v 6.1 --style raw --s 50 --q 2
```

参数说明：
- `--ar 1:1`：正方形
- `--v 6.1`：最新版本
- `--style raw`：减少风格化，更写实
- `--s 50`：风格化程度中等
- `--q 2`：高质量

---

## 五、Flux / SD 提示词建议

如果是 Flux / Stable Diffusion，可以拆成**正向 + 反向**提示：

**正向**：
```
masterpiece, best quality, app icon design, square format, deep navy night sky, 
snow-capped mountain, golden wisdom halo, tiny silhouette of lantern-carrying 
climber, climbing trail with footprints, minimalist, atmospheric, professional, 
warm golden light, dark navy, white snow, no text, no animals
```

**反向（避免元素）**：
```
cartoon, cute animal, duck, bird, text, watermark, blurry, low quality, 
deformed, ugly, multiple people, daylight
```

**采样参数**（SD）：
- Steps: 30
- CFG Scale: 7
- Sampler: DPM++ 2M Karras
- Size: 1024x1024

---

## 六、生图后的处理建议

生图后还需要：

1. **抠出主体 + 套圆角**：用 Photoshop 或 Figma 把生图结果做 28px 圆角
2. **背景纯色化**：把背景替换为深蓝渐变（确保缩到 144×144 时仍清晰）
3. **对比度调整**：拉大学子剪影与雪山的对比度，避免缩小后看不清
4. **导出多尺寸**：
   ```bash
   rsvg-convert -w 144 -h 144 source.png -o avatar_logo_144.png
   rsvg-convert -w 256 -h 256 source.png -o avatar_logo_256.png
   rsvg-convert -w 512 -h 512 source.png -o avatar_logo_512.png
   ```

---

## 七、推荐生图工具优先级

| 工具 | 中文支持 | 风格契合度 | 推荐度 |
|------|---------|----------|-------|
| **即梦 (字节)** | ✅ | ⭐⭐⭐⭐⭐ | 🥇 首选 |
| **通义万相 (阿里)** | ✅ | ⭐⭐⭐⭐ | 🥈 备选 |
| **文心一格 (百度)** | ✅ | ⭐⭐⭐ | 🥉 国内可用 |
| **Midjourney v6.1** | ❌(英) | ⭐⭐⭐⭐⭐ | 国际首选 |
| **DALL-E 3** | ❌(英) | ⭐⭐⭐⭐ | 备选 |
| **Flux.1 dev** | ❌(英) | ⭐⭐⭐⭐ | 写实最强 |
| **Seedream 4.0** | ✅ | ⭐⭐⭐⭐⭐ | 如果你的 Trae 接入了 |

---

## 八、当前可用的离线方案

如果你想立刻拿到头像，可以继续使用我已经生成的 SVG 版本：

- [avatar_logo.svg](computer:///Users/wangliping/Public/selfProgram/ielts_apply_seek/docs/miniprogram/W9/屠鸭口语磨炼-提报材料/avatar_logo.svg)
- [avatar_logo_144.png](computer:///Users/wangliping/Public/selfProgram/ielts_apply_seek/docs/miniprogram/W9/屠鸭口语磨炼-提报材料/avatar_logo_144.png)（10.4 KB）

这个版本已经是：
- ✅ 深蓝夜空 + 雪山 + 学子剪影 + 提灯 + 脚印
- ✅ 圆角 28px
- ✅ 144/256/512 三尺寸齐备
- ✅ 直接可上传到微信公众平台

---

## 九、未来若 GetImage tool 可用

当前 Trae 会话没有 GenerateImage MCP 工具可用。如果你想让我直接生图，需要：

1. **启用 Seedream 插件**（系统设置 → 插件 → 启用 Seedream）
2. **配置 GenerateImage MCP 服务器**（设置 → MCP → 添加 seedream 服务器）
3. **配置 API Key**（即梦 / Seedream 官方）

完成后告诉我"已启用生图工具"，我会重新调用生图并把结果保存到当前目录。
