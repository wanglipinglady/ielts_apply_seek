# 阶段 11:语音训练工坊(每日跟读闭环)— 产品需求文档(PRD)

> 状态:待用户确认(确认后按 phase-11-voice-training-design.md 实施)
> 优先级:高 — 用户备考主线的每日核心循环,替代 Enjoy 积分制依赖
> 版本:v1.0(2026-11-04)

## 0. 目录

1. 需求背景 2. 需求目标 3. 用户故事 4. 功能范围与边界
5. 功能需求详述(M1-M5) 6. 非功能需求 7. 里程碑 8. 验收标准

## 1. 需求背景

### 1.1 业务触发

用户当前每日训练循环(见 `ielts_1000h_journal/PLAN.md`):

```
中文感想 → Enjoy Craft 改写成英文 → 查音标 → TTS 听音 → 跟读录音 → 对比纠音
```

该循环目前依赖 Enjoy 网页版,存在三个问题:
1. **积分制**:Craft 改写与 TTS 消耗积分,长期使用需付费订阅
2. **数据外流**:训练记录(改写文本、录音、纠错)不在本系统,无法与错词本、复习队列联动
3. **流程割裂**:需在 Enjoy 与本站之间切换,与"dogfooding 自建工具"的既定策略矛盾

### 1.2 既有能力盘点(2026-11-04 实测代码)

| 能力 | 现状 | 本期是否复用 |
|---|---|---|
| LLM 调用(改写) | `llm_service.py`,openai SDK + MiniMax,已有结构化输出/dry-run 模式 | **复用**,仅加 prompt |
| TTS | `listening_tts_service.py`,MiniMax T2A v2(积分制) | **保留为回退**,主路径换免费方案 |
| ASR 转写 | `whisper_service.py`,pywhispercpp,已解决 webm/opus 归一化 | **复用**(V2) |
| 中英翻译 | `translation_client.py`,MyMemory 免费接口 | 备用 |
| 音标解析 | **无** | **新建** M3 |
| 免费高质量 TTS | **无**(MiniMax 积分) | **新建** M2(edge-tts) |
| 训练记录页 | **无** | **新建** M4/M5 |

### 1.3 核心决策

- **TTS 主路径选 edge-tts**(微软在线神经音,免费无 key,音质与 Enjoy 同源)。
  风险:非官方接口,理论可关停 → 封装 provider 接口,回退链
  `edge-tts → MiniMax T2A(既有) → 明文报错`,与 listening_tts_service 的降级风格一致。
- **音素级 AI 打分(纠音)划入 V2**,走 Azure Speech 发音评估免费层(F0,约 5 音频小时/月,注册时核实)。
  MVP 的"纠音"= TTS 参考音与用户录音的 A/B 对听 + 人工填纠音表(journal `daily/` 模板第 4 节)。

## 2. 需求目标

### 2.1 业务目标

1. 每日跟读闭环 100% 在本系统内完成,**零积分/零新增订阅成本**
2. 训练记录落库,与 journal 打卡、错词本形成证据链
3. 全流程(输入中文→听到自己录音)≤ 3 分钟,降低执行摩擦即提高 132 天的坚持概率

### 2.2 成功指标

| 指标 | 目标 | 度量方式 |
|---|---|---|
| 每日训练完成率 | ≥ 80%(连续 30 天口径) | voice_training_records 按日计数 vs journal daily/ |
| 积分消耗 | 0(MVP 范围内) | 全流程不触达任何积分接口 |
| 单次流程耗时 | ≤ 3 分钟 | 前端埋点(创建记录→录音提交) |
| TTS 可用性 | edge-tts 失败自动回退,不阻塞流程 | 服务日志回退计数 |

### 2.3 非目标

- 不做音素级 AI 打分(V2,Azure)
- 不做多用户(单用户系统,与现网一致)
- 不做移动端适配(碎片场景继续用小程序口语畅聊)
- 不替换既有 MiniMax TTS 调用点(听力题库不动,只给新模块用 edge-tts)

## 3. 用户故事

### US1:晚间开始今日跟读
打开语音训练页 → 粘贴今天的中文感想(100-150 字)→ 选择风格(自然/口语/正式)→ 点击"改写"→ 3-5 秒后看到英文文本,可一键重生成。

### US2:查音标
改写完成后自动展示逐词 IPA(美式为主、英式并列)→ 点击任意词可听单词发音、看拼读规则说明(LLM 生成,缓存)→ 不认识的词一键加入错词本。

### US3:听标准音
点击"生成语音"→ 播放器出现整段英文神经音(可调 0.5x-1x 语速)→ 可逐句播放。

### US4:跟读录音
点击"跟读"→ 浏览器录音(webm/opus)→ 停止后自动保存 → 页面提供参考音/录音 A/B 连播对比。

### US5:记录与打卡
每次训练自动落一条记录(源中文、英文、风格、音标 JSON、音频路径)→ 历史列表可回看、重听任意一天的对比 → 复制当天内容到 journal `daily/` 模板。

## 4. 功能范围与边界

### 4.1 功能范围(本期 MVP)

| 模块 | 内容 |
|---|---|
| M1 | LLM 改写服务(中文段落 → 三风格英文) |
| M2 | edge-tts 免费语音合成服务(带缓存与回退链) |
| M3 | 音标/拼读解析服务(逐词 IPA + 拼读规则说明) |
| M4 | 跟读录音(浏览器录音、存储、A/B 对比播放) |
| M5 | 训练记录(落库、历史列表、journal 联动) |

### 4.2 非范围(V2 及以后)

- Azure 发音评估(音素级准确度分、纠音建议)— V2
- 录音 ASR 转写展示(whisper 已具备,接口留好但 UI 不做)— V2
- 逐句强制对齐(词级时间戳高亮)— V3
- 训练页与艾宾浩斯复习队列的自动联动 — V3

### 4.3 边界与约束

1. 单段文本 ≤ 500 词(超限前端拦截,后端 400)
2. 录音 ≤ 3 分钟/条,存储 `~/.ielts-buddy/voice/recordings/`,webm 原格式
3. TTS 音频缓存 `~/.ielts-buddy/voice/tts/`,key = sha256(text+voice+speed),命中即不重复合成
4. LLM 改写失败不阻塞:提示重试,不计为失败记录
5. edge-tts 依赖出站网络;服务器(118.190.148.121)需放行 `speech.platform.bing.com` 出站
6. 系统依赖:espeak-ng(macOS:brew / Ubuntu:apt),缺失时 M3 降级为"仅 CMUdict 词表模式"

## 5. 功能需求详述

### 5.1 M1:LLM 改写服务

- 输入:`{ zh_text, style: natural|casual|formal }`
- 输出:`{ en_text, word_count }`
- 复用 `llm_service.py` 的 client;prompt 要求:地道美式、保留原意、难度匹配 B1 学习者(避免超纲词汇)、不加解释
- 同一输入可重生成(temperature 默认 0.7)

### 5.2 M2:edge-tts 语音合成服务

- 输入:`{ en_text, voice: en-US-...|auto, speed: 0.5-2.0 }`
- 输出:mp3 文件路径(缓存命中直接返回)
- 主路径 `edge-tts` 库(异步);失败重试 1 次 → 回退 MiniMax T2A → 仍失败返回结构化错误
- 默认音色:`en-US-AriaNeural`(女)与 `en-US-GuyNeural`(男)二选一,存用户偏好

### 5.3 M3:音标解析服务

- 输入:英文文本
- 输出:逐词数组 `[{ word, ipa_us, ipa_uk, phonemes[], rule? }]`
- 词级 IPA:CMUdict 优先(打包于依赖 `pronouncing`),查不到 → espeak-ng(phonemizer)
- 拼读规则说明:LLM 生成一次并缓存(按词),内容 = 该词的字母组合→音素对应关系一句话
- 生词按钮:调既有错词本接口

### 5.4 M4:跟读录音

- 前端 MediaRecorder(webm/opus),录完 `multipart/form-data` 上传
- 存储路径:`~/.ielts-buddy/voice/recordings/{record_id}.webm`
- A/B 对比:前端双 audio 元素连播(参考音→0.5s 间隔→录音),不做服务端混音

### 5.5 M5:训练记录

- 表 `voice_training_records`(双后端 SQLite/MySQL,遵循 repository 模式)
- 列:id, user_id, source_zh TEXT, rewritten_en TEXT, style VARCHAR(16),
  ipa_json TEXT, tts_voice VARCHAR(32), tts_path TEXT, recording_path TEXT,
  notes TEXT, created_at DATETIME
- 历史页:按日倒序,支持回放与"复制为 journal 模板格式"(Markdown 剪贴板)

## 6. 非功能需求

- 权限:登录用户(复用 auth/deps)
- 成本:运行时现金成本 0;LLM 仅文本 token(月成本 < ¥5 量级)
- 可用性:任一外部依赖(LLM/edge-tts/espeak)失败不白屏,均有降级路径
- 隐私:录音仅本机/自有服务器,不出第三方(区别于 Enjoy 的关键优势)

## 7. 里程碑(两个周末)

| 批次 | 内容 | 产出 |
|---|---|---|
| D1 | M2 edge-tts + M3 音标解析 | 两个可单测的服务模块 |
| D2 | M1 改写 + 路由 + 表 | API 全通(Swagger 自测) |
| D3 | 前端五步训练页 + 联调 | 全流程走通 |
| D4 | 历史页 + journal 复制 + 缓冲 | MVP 验收 |

## 8. 验收标准

1. 五步全流程(中文→改写→音标→语音→录音对比)本系统内完成,≤ 3 分钟
2. 全流程 0 积分接口调用
3. edge-tts 断网模拟 → 自动回退 MiniMax 且页面不报错
4. 训练记录落库,历史可回放当日双音频
5. 生词可一键入错词本
6. 与 PLAN.md 每日例程对齐:当晚即可用新工具完成第一次打卡

---
配套详细设计:`phase-11-voice-training-design.md`
