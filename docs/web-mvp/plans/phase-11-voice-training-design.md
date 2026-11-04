# 阶段 11:语音训练工坊 — 详细设计文档

> 对应 PRD:`phase-11-voice-training-prd.md`
> 原则:全部遵循既有工程惯例(repository 双后端、服务层单例 lazy、LLM dry-run、
> whisper 归一化等),不引入新框架。版本:v1.0(2026-11-04)

## 1. 架构总览

```
┌─────────────── 前端 pages/voice_training(新) ───────────────┐
│ ① 中文输入+风格  ② 音标面板  ③ 音频播放  ④ 录音对比  ⑤ 历史   │
└──────────────┬──────────────────────────────────────────────┘
               │ /api/voice-training/*
┌──────────────┴──────────────────────────────────────────────┐
│ router: web/routers/voice_training.py(新,瘦层)              │
├─────────────────────────────────────────────────────────────┤
│ 服务层                                                        │
│ ├─ craft_rewrite_service.py(新) ──→ llm_service(既有)        │
│ ├─ voice_tts_service.py(新)  ──→ edge-tts →回退→ MiniMax T2A │
│ ├─ phonetics_service.py(新)  ──→ CMUdict/pronouncing →      │
│ │                              回退→ phonemizer(espeak-ng)   │
│ │                              + LLM 规则说明(缓存)          │
│ └─ voice_record_service.py(新) ──→ 存储层                    │
├─────────────────────────────────────────────────────────────┤
│ 存储层: repositories(sqlite_repo/mysql_repo 加一张表)       │
│ 文件:   ~/.ielts-buddy/voice/{tts,recordings}/              │
└─────────────────────────────────────────────────────────────┘
```

关键决策:每块积木独立成 service(与 speaking/whisper 同风格),
router 只做参数校验与编排,便于 V2 在 record 提交后挂 Azure 评估。

## 2. 依赖清单

| 依赖 | 用途 | 安装 | 许可/风险 |
|---|---|---|---|
| `edge-tts` (pip) | 免费微软神经音 TTS | `pip install edge-tts` | 非官方接口,已用回退链兜底 |
| `pronouncing` (pip) | CMUdict 词级音素(ARPAbet) | `pip install pronouncing` | 纯 Python,内置词表,MIT |
| `phonemizer` (pip) | espeak-ng 后端 IPA 整段转写 | `pip install phonemizer` | MPL2.0 |
| espeak-ng(系统) | phonemizer 后端 | mac:`brew install espeak-ng`<br>ubuntu:`apt install espeak-ng` | 缺失时 M3 降级运行 |
| `openai` (既有) | LLM 改写/规则说明 | 已在依赖 | — |
| `httpx` (既有) | edge-tts 内部亦走 httpx | 已在依赖 | — |

**IPA 转换说明**:CMUdict 输出 ARPAbet(如 `S K EH D ZH UW L IH NG`),
服务内置静态映射表 `arpabet_to_ipa.py`(ARPAbet→美式 IPA,含重音标记
`ˈ/ˌ`)。espeak-ng 直接输出 IPA,用于 CMUdict 未收录词。
英美双标:espeak-ng `en-US`/`en-GB` 各跑一遍;CMUdict 词取 espeak 的 UK 版补全。

## 3. 数据模型

`src/ielts_buddy/core/models.py` 增加:

```python
class VoiceTrainingRecord(Base):
    __tablename__ = "voice_training_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    source_zh = Column(Text, nullable=False)          # 中文原文
    rewritten_en = Column(Text, nullable=False)        # LLM 改写
    style = Column(String(16), default="natural")     # natural|casual|formal
    ipa_json = Column(Text, nullable=True)             # M3 输出(JSON 字符串)
    tts_voice = Column(String(32), default="en-US-AriaNeural")
    tts_path = Column(String(255), nullable=True)     # 相对 ~/.ielts-buddy
    recording_path = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)                # 纠音备注(手动)
    created_at = Column(DateTime, server_default=func.now())
```

迁移:遵循现有建表方式(SQLite 自动 create_all;MySQL 手动 DDL 同步,
与既有表一致的幂等脚本)。repo 层在 `sqlite_repo.py`/`mysql_repo.py`
各加 5 个方法:`create_voice_record / get_voice_record / list_voice_records
(count_user_voice_records) / attach_recording / attach_tts`。
接口定义加入 `core/repository.py` 抽象基类(fallback_repo 同步实现)。

## 4. API 设计(全部挂现有鉴权依赖 `get_current_user`)

### 4.1 路由总表 `web/routers/voice_training.py`

| # | 方法 | 路径 | 功能 | 请求 → 响应 |
|---|---|---|---|---|
| 1 | POST | /api/voice-training/rewrite | 中文→英文改写 | `{zh_text, style}` → `{record_id, en_text, word_count}` |
| 2 | POST | /api/voice-training/{id}/phonetics | 音标解析 | `{}` → `{words: [{word, ipa_us, ipa_uk, phonemes[], rule?}]}` |
| 3 | POST | /api/voice-training/{id}/tts | 合成参考音 | `{speed?}` → `{tts_path, cached, provider}` |
| 4 | POST | /api/voice-training/{id}/recording | 上传跟读录音 | multipart(audio) → `{recording_path, duration}` |
| 5 | GET  | /api/voice-training/{id}/audio/{kind} | 取音频流 | kind=tts\|recording → `FileResponse`(Range 支持) |
| 6 | GET  | /api/voice-training/records | 历史列表 | `?page=&size=` → `{items[], total}` |
| 7 | PATCH | /api/voice-training/{id} | 补 notes | `{notes}` → `{ok}` |
| 8 | GET  | /api/voice-training/{id}/journal-format | journal 模板文本 | → `{markdown}`(按 daily.md 模板拼装) |

### 4.2 关键接口细节

**#1 rewrite**:创建记录(zh/style 先落库,拿到 record_id);
LLM 失败时记录仍保留(status 由后续调用自然体现),返回 200 + `en_text=null`
+ `retryable: true`,前端提示重试。风格校验白名单。
字数限制:zh_text ≤ 800 字符,en_text word_count ≤ 500。

**#3 tts**:body 的 speed 归一 [0.5, 2.0],默认 1.0。
cache key:`sha256(text + voice + speed)`。响应 `provider` 字段暴露
`edge|minimax`,便于观察回退率。文件:`tts/{sha}.mp3`。

**#4 recording**:限 webm/opus(`Content-Type` 校验),大小 ≤ 10MB。
存 `recordings/{record_id}_{n}.webm`(n=该记录第 n 次上传,旧文件保留,
最新一次为对比对象;LATER 清理策略:仅保留最近 3 个)。

**#5 audio**:静态文件走 `FileResponse` + `Accept-Ranges`,
录音播放需要 Range(否则 iOS Safari 拖动异常)。路径白名单校验防穿越。

**#8 journal-format**:把 record 拼成 journal daily 模板 1/2 节的
Markdown(`> 中文原文` + 英文文本),前端一键复制,粘贴进
`ielts_1000h_journal/daily/`。

### 4.3 错误码约定(沿用现有 HTTPException 风格)

| 场景 | 状态码 | detail |
|---|---|---|
| zh_text 超长/为空 | 422 | VALIDATION_FAILED |
| LLM 改写失败 | 200 + retryable:true(不 500,保记录) | — |
| edge-tts 与 MiniMax 均失败 | 503 | TTS_UNAVAILABLE |
| espeak-ng 缺失且词不在 CMUdict | 200 + word.ipa=null | 降级 |
| 录音格式/大小不合规 | 422 | INVALID_RECORDING |

## 5. 服务设计

### 5.1 craft_rewrite_service.py

```
@dataclass RewriteResult: en_text, word_count
async def rewrite(zh_text, style) -> RewriteResult
  prompt: system="You are an English writing coach for a B1-level
    Chinese learner. Rewrite the user's Chinese diary entry as natural
    {style} American English. Keep the meaning. Use vocabulary a B1
    learner can understand (avoid rare words). Output ONLY the English
    text, no explanations, no quotes."
  复用 llm_service 的 client/dry-run:无 key 时返回 mock 句
  ("[dry-run] Today I ..."),前端可演示。
```

### 5.2 voice_tts_service.py(核心新模块)

```
async def synthesize(text, voice, speed) -> SynthResult(path, provider, cached)
  1. key = sha256(text+voice+speed);若 tts/{key}.mp3 存在 → cached=True 直接返回
  2. edge-tts 主路径:
       communicate = edge_tts.Communicate(text, voice, rate=f"+{int((speed-1)*100)}%")
       流式写文件(异步迭代 audio chunk)
  3. 异常(超时 30s/网络/4xx)→ logger.warning → 调 MiniMax T2A(复用
     listening_tts_service 的 _extract_audio_bytes 逻辑,提取为公共函数)
  4. 再失败 → raise TTSServiceUnavailable
单测:mock edge_tts.Communicate;断言缓存命中不再外呼;断言回退链顺序。
```

音色白名单:`en-US-AriaNeural / en-US-GuyNeural / en-GB-SoniaNeural`
(听英音参考用,与新概念英音轨对齐)。

### 5.3 phonetics_service.py

```
def parse(text) -> list[WordPhonetics]
  分词:正则 [A-Za-z']+ 小写化;保留词序与原词形
  对每词:
    1. cmu = pronouncing.phones_for_word(w) 取第一
    2. cmu 命中 → arpabet_to_ipa(cmu) → ipa_us;ipa_uk 由 espeak GB 得
    3. cmu 未命中 → phonemizer(espeak en-US/en-GB 各一次)
    4. phonemes 数组 = ipa 逐符号切分(元音/辅音字符集正则)
    5. rule 字段 lazy:仅当 record 持久化后前端点开某词时单独请求
       GET /api/voice-training/word-rule?word=xx → LLM 一句话规则 →
       word_rules 表(或 ipa_json 内嵌缓存)→ 第二次起零成本
停止词跳过规则生成(高频功能词无教学价值:the/a/of/to...)
```

`arpabet_to_ipa.py`:静态映射表 + 重音处理(ARPAbet 数字重音 → ˈ/ˌ),
约 40 行,一次性写死带单测(抽样 50 词与剑桥词典人工比对)。

### 5.4 voice_record_service.py

薄封装:路径生成、sha 校验、`attach_recording` 落库。
音频时长由前端记录(录音时已知),不做服务端探测(V2 才需要)。

## 6. 前端设计(pages/voice_training,遵循现有模板体系)

```
Step ① 输入区   textarea(中文) + 风格三选 + [改写] 按钮
Step ② 结果区   en_text + [重新生成] + 字数
       音标面板  逐词 chips;点击展开(ipa_us/ipauk/phonemes/rule)
       + [加入错词本](调既有接口) + [试听单词](V2:若 espeak 可用先不做)
Step ③ 语音区   [生成语音] → audio 播放器 + 语速滑块 + 音色切换
Step ④ 录音区   [开始跟读]/[停止] → 录音播放器 + [A/B 连播](参考音→录音)
       + [保存对比]/[重录]
Step ⑤ 收尾     notes 输入(纠音备注) + [复制 journal 模板] + 自动进历史
```

- 录音:`navigator.mediaDevices.getUserMedia` + `MediaRecorder`
  (mimeTypes 白名单里挑 `audio/webm;codecs=opus`,Safari 降级 mp4/aac —
  后端一并放行 mp4)
- A/B 连播:纯前端双 `<audio>` 顺序播放,中间 300ms 静音
- 所有按钮防抖 + loading 态;LLM/edge-tts 失败均为内联提示,不弹窗

## 7. 配置项(config.py 新增,均有默认值)

| 键 | 默认 | 说明 |
|---|---|---|
| VOICE_TTS_PROVIDER | auto | auto=edge→minimax;可强指 |
| VOICE_TTS_TIMEOUT | 30 | 秒 |
| VOICE_DEFAULT_VOICE | en-US-AriaNeural | |
| VOICE_RECORDING_MAX_MB | 10 | |
| VOICE_TEXT_MAX_WORDS | 500 | |
| ESPEAK_MISSING_OK | true | 缺 espeak 不阻塞启动 |

## 8. 测试与验收清单

**单测(tests/test_contracts/ 新增 test_voice_contract.py)**
- [ ] rewrite:LLM 成功/dry-run/超长 422
- [ ] tts:缓存命中/edge 失败回退 minimix/provider 字段正确
- [ ] phonetics:CMUdict 命中词(Aria→/əˈriːə/)、未命中降级、
      ipa 为 null 不 500
- [ ] recording:webm 保存、路径落库、>10MB 拒绝
- [ ] records:分页、journal-format 输出含源中文与英文

**人工验收(与 manual-verify 惯例一致,新增 manual-verify-phase-11.md)**
- [ ] 真实中文 150 字全流程 ≤ 3 分钟
- [ ] 断网 edge-tts(改 hosts 模拟)→ 回退成功且日志可查
- [ ] 移动端浏览器可录音(iOS Safari 实机)
- [ ] journal-format 粘贴进 daily/2026-11-XX.md 格式无损
- [ ] 服务器(Ubuntu)espeak-ng 安装后 espeak 路径正常

## 9. V2 预留(本期只留接口,不实现)

`POST /{id}/assessment`(Azure 发音评估):
- 前端上传录音后异步触发;结果写 `ipa_json` 同级新列 `assessment_json`
- 服务:`azure_speech_service.py`(azure-cognitiveservices-speech SDK)
- 免费层 F0 约 5 音频小时/月 — **注册时核实当前额度**
- 评估结果与 M3 音素表叠加显示:参考 ipa vs 实际得分音素高亮
- 录音格式要求 azure SDK 可直接吃 webm? 否 — 需 ffmpeg 转 wav,
  复用 whisper_service 的归一化管线

## 10. 实施顺序(对齐 PRD 里程碑)

1. models + repo 双后端 + fallback(半天)
2. voice_tts_service + 单测(1 天)
3. phonetics_service + arpabet_to_ipa + 单测(1 天)
4. craft_rewrite_service + router 全接口(半天)
5. 前端训练页(1 天)
6. 历史页 + journal-format + manual-verify 文档(半天)
7. 服务器部署:apt espeak-ng、放行出站、systemd 重启(半小时)
