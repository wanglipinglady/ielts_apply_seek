"""Whisper.cpp ASR 服务(v3.7 P1 新增)。

封装 ``pywhispercpp``(whisper.cpp 的 Python binding):
- Apple Silicon 优先用 Core ML(Apple Neural Engine)走 ANE 加速
- 失败回退到本地 CPU(NumPy 即可,无需 GPU)
- 完全不可用时给 mock fallback(空 transcript + 空 tokens),
  让 UI 仍能继续走完「评分」管道,前端 demo 不被打断

设计要点:
- 同步阻塞调用 → web 层走 ``asyncio.to_thread`` 转异步
- Lazy 单例(@lru_cache),首次 transcribe 才下载/编译
- 媒体格式归一化:浏览器 webm/opus → ffmpeg 转 16kHz mono WAV → whisper
  处理;若 ffmpeg 缺失则尝试直接传 webm(whisper.cpp 也支持常见格式)

依赖:
  pip install pywhispercpp
  brew install ffmpeg    # macOS 转码用

PRD: docs/web-mvp/plans/phase-8-speaking-practice.md §5.2
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    """whisper 转写结果(同步返回)。"""

    text: str
    """完整转写文本(空格分隔词)。"""

    tokens: list[dict] = field(default_factory=list)
    """词级时间戳:[{word, t0_ms, t1_ms, prob}, ...]。"""

    audio_duration_sec: float = 0.0
    """音频时长(s),由 ffmpeg 或 whisper 给出。"""

    used_core_ml: bool = False
    """本机是否启用 Core ML 加速(只对 Apple Silicon 有效)。"""

    model_id: str = ""
    """实际加载的模型名(如 small.en)。"""

    language: str = "en"
    """识别语种(本次固定 en,不开放切换)。"""

    fallback: bool = False
    """是否走了 mock fallback(whisper 不可用)。"""


def _is_apple_silicon() -> bool:
    """简单判断当前是否 Apple Silicon。

    通过 ``platform.machine()`` 取 arch;Apple Silicon 返回 "arm64"。
    注意 Intel Mac 也会返回 x86_64,不参与 Core ML 加速。
    """
    import platform
    return platform.machine() == "arm64"


def _has_ffmpeg() -> bool:
    """检查 ffmpeg 是否在 PATH(转 webm→wav 用)。"""
    return shutil.which("ffmpeg") is not None


def _convert_webm_to_wav(webm_path: str) -> Optional[str]:
    """ffmpeg:任意格式 → 16kHz mono PCM WAV。

    whisper.cpp 要求输入是 16kHz mono PCM(原始 -c:a pcm_s16le)。

    Returns:
        输出 wav 路径;失败返回 None。
    """
    if not _has_ffmpeg():
        logger.warning("[whisper] ffmpeg 未安装,跳转换码")
        return None

    out_path = tempfile.NamedTemporaryFile(
        suffix=".wav", delete=False, dir="/tmp"
    ).name
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", webm_path,
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        out_path,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=30)
        return out_path
    except subprocess.CalledProcessError as exc:
        logger.warning("[whisper] ffmpeg 转码失败: %s", exc)
        return None
    except subprocess.TimeoutExpired:
        logger.warning("[whisper] ffmpeg 转码超时")
        return None


def _wav_duration(wav_path: str) -> float:
    """用 ffprobe 读 wav 时长(s)。失败回退 0。"""
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", wav_path],
            check=True, timeout=5, capture_output=True, text=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


class WhisperService:
    """whisper.cpp ASR 同步服务。

    Args:
        model: 模型名,默认 ``small.en``(PRD §4.2 决策)。
        language: 强制英文,固定 ``en``。
        core_ml: 是否在 Apple Silicon 上启用 ANE 加速。
            非 Apple Silicon 自动忽略。
        n_threads: whisper.cpp CPU 推理线程数(M4 8 核建议 4)。
    """

    def __init__(
        self,
        model: str = "small.en",
        language: str = "en",
        core_ml: bool = True,
        n_threads: int = 4,
    ) -> None:
        # model 可以是：
        #   - 内置名（'small.en' / 'tiny.en' ...）→ pywhispercpp 解析
        #   - **完整文件路径** → 直接加载（服务器上模型是手动从 ModelScope
        #     下载的，文件名不在 pywhispercpp 的白名单里，只能走路径）
        self._model_name = model
        self._language = language
        self._core_ml_enabled = core_ml and _is_apple_silicon()
        self._n_threads = n_threads
        self._model = None
        self._init_err: Optional[str] = None
        # pywhispercpp 版本差异：词级时间戳参数名（token_timestamps / word_timestamps）
        self._ts_kwarg: Optional[str] = None

    # ---- 状态 ----
    def is_available(self) -> bool:
        """whisper SDK 是否可用 + 模型是否加载成功。"""
        try:
            from pywhispercpp.model import Model  # noqa: F401
        except ImportError:
            return False
        if self._model is None and self._init_err is None:
            self._init()
        return self._model is not None

    def model_id(self) -> str:
        return self._model_name

    def used_core_ml(self) -> bool:
        return self._core_ml_enabled and self._model is not None

    # ---- 转写 ----
    def transcribe(self, audio_path: str) -> TranscriptResult:
        """同步转写,返回 TranscriptResult。

        失败 → 返回 mock fallback(transcript="", tokens=[], fallback=True),
        让上层业务代码继续走流程;不抛异常,不阻塞 web 链路。
        """
        audio_path_obj = Path(audio_path)
        if not audio_path_obj.exists():
            logger.warning("[whisper] audio not found: %s", audio_path)
            return self._mock_result(audio_path)

        # 1) 预处理:webm/opus → 16kHz mono WAV
        wav_path: Optional[str] = None
        if _has_ffmpeg() and audio_path_obj.suffix.lower() != ".wav":
            wav_path = _convert_webm_to_wav(audio_path)
        if wav_path is None:
            wav_path = audio_path  # 直接传(whisper.cpp 也容错处理常见格式)

        duration = _wav_duration(wav_path)

        # 2) 确保模型已加载
        if not self.is_available():
            return self._mock_result(audio_path, duration=duration)

        # 3) 转写
        #
        # pywhispercpp 版本差异（踩过的坑）：
        #   1.5.x 把 `word_timestamps` 改名为 `token_timestamps`，
        #   传旧参数会抛 "'whisper_full_params' object has no attribute
        #   'word_timestamps'" → 转写直接失败 → 走 mock fallback（空转写）。
        # 这里按能力探测传参，两个版本都能跑。
        transcribe_kwargs = {
            "language": self._language,
            "n_threads": self._n_threads,
            "print_progress": False,
            "print_realtime": False,
            "print_timestamps": False,
            # v4.0 关键：必须给 initial_prompt 锚定英语。
            # 生产用的 KBLab/kb-whisper-small 是**多语言**权重（不是 .en 变体），
            # 光传 language='en' 不够 —— 实测会输出瑞典语：
            #   "Godmorgon. Jag heter Wang. Jag bor i Chengdu ..."
            # 加上英语 initial_prompt 后才正常输出：
            #   "Good morning, my name is Wang. I live in Chengdu ..."
            "initial_prompt": self._english_prompt(),
        }
        ts_flag = self._detect_timestamp_kwarg()
        if ts_flag:
            transcribe_kwargs[ts_flag] = True

        try:
            segments = self._model.transcribe(wav_path, **transcribe_kwargs)
        except TypeError:
            # 老版本不支持 token_timestamps → 退到 word_timestamps
            legacy = dict(transcribe_kwargs)
            legacy.pop(ts_flag, None)
            legacy["word_timestamps"] = True
            try:
                segments = self._model.transcribe(wav_path, **legacy)
            except Exception as exc:
                logger.warning("[whisper] transcribe failed: %s", exc)
                return self._mock_result(audio_path, duration=duration)
        except Exception as exc:
            logger.warning("[whisper] transcribe failed: %s", exc)
            return self._mock_result(audio_path, duration=duration)

        # 4) 解析 segments → 文本 + tokens
        text_parts: list[str] = []
        tokens: list[dict] = []
        for seg in segments:
            text_parts.append(getattr(seg, "text", "") or "")
            # 各版本 pywhispercpp 字段名略有差异,做兼容
            words = getattr(seg, "words", None) or []
            for w in words:
                tokens.append({
                    "word": getattr(w, "word", "") or getattr(w, "text", ""),
                    "t0_ms": int(getattr(w, "t0", 0) * 1000),
                    "t1_ms": int(getattr(w, "t1", 0) * 1000),
                    "prob": float(getattr(w, "probability", 0.0)
                                  or getattr(w, "prob", 0.0) or 0.0),
                })

        transcript = " ".join(t.strip() for t in text_parts if t.strip())
        # 清理临时 wav
        if wav_path != audio_path:
            try:
                Path(wav_path).unlink(missing_ok=True)
            except Exception:
                pass

        return TranscriptResult(
            text=transcript,
            tokens=tokens,
            audio_duration_sec=duration,
            used_core_ml=self.used_core_ml(),
            model_id=self._model_name,
            language=self._language,
            fallback=False,
        )

    # ---- 内部 ----

    def _resolve_model_arg(self) -> str:
        """把配置里的模型名解析成 pywhispercpp 能用的参数。

        pywhispercpp 的 ``resolve_model_path`` 规则：
        1. model_name 是**存在的文件路径** → 直接用
        2. 在 models_dir 里找 model_name / model_name.bin
        3. 都没有 → 去 huggingface.co 下载（服务器连不上，会失败）

        生产环境的 ggml 模型是从 ModelScope 手动下载的，
        文件名（ggml-small-multi.bin）不在 pywhispercpp 的
        AVAILABLE_MODELS 白名单里 → 走规则 2 找不到 → 规则 3 下载失败。
        所以这里把**存在的文件路径**直接传进去，命中规则 1。
        """
        from pathlib import Path

        # 只有"看起来像路径"（含分隔符或以 ~ 开头）才当路径处理。
        # 否则纯模型名（如 'small-multi'）走下面的 models_dir 查找 ——
        # 直接 Path('small-multi').is_file() 会去 stat 相对路径，
        # 而生产服务的 cwd 是 /root（admin 用户无权访问）→ PermissionError。
        raw = self._model_name
        if raw.startswith("~") or "/" in raw:
            candidate = Path(raw).expanduser()
            try:
                if candidate.is_file():
                    return str(candidate.resolve())
            except OSError:
                pass

        # 非路径：按"名字"找。
        #
        # v4.0 修正：之前硬编码 "/root/.local/share/pywhispercpp/models"，
        # 但生产服务的 uvicorn 是以 **admin** 用户跑的（systemd 配了 User=admin），
        # admin 读不了 /root → "[Errno 13] Permission denied"
        # → 模型加载失败 → 转写永远走 mock fallback（空转写）。
        # 现在按优先级找：环境变量 → 当前运行用户的家目录 → /root（兼容 root 运行）。
        candidates_dirs = []
        env_dir = os.environ.get("IELTS_BUDDY_WHISPER_MODELS_DIR", "").strip()
        if env_dir:
            candidates_dirs.append(Path(env_dir))
        home = os.path.expanduser("~")
        if home and home != "/root":
            candidates_dirs.append(Path(home) / ".local/share/pywhispercpp/models")
        candidates_dirs.append(Path("/root/.local/share/pywhispercpp/models"))

        for models_dir in candidates_dirs:
            for name in (self._model_name, f"ggml-{self._model_name}.bin",
                         f"ggml-{self._model_name}"):
                p = models_dir / name
                try:
                    if p.is_file():
                        return str(p.resolve())
                except OSError:
                    continue

        # 都找不到 → 交回 pywhispercpp 自己处理（可能触发下载）
        return self._model_name

    def _english_prompt(self) -> str:
        """给 whisper 的英语提示（锚定输出语种）。

        为什么需要：
        生产环境的 ggml 模型来自 ModelScope 的 KBLab/kb-whisper-small，
        那是**多语言**权重。whisper.cpp 对多语言权重即使传了 language='en'，
        也可能因为声学歧义输出其它语种（实测瑞典语）。
        给一段英语 initial_prompt 可以把解码锚定到英语。

        真正的 .en 权重（tiny.en）加这个也无害。
        """
        return (
            "The following is a spoken English answer to an IELTS speaking "
            "question. The speaker is describing their experience."
        )

    def _detect_timestamp_kwarg(self) -> Optional[str]:
        """探测当前 pywhispercpp 版本用哪个词级时间戳参数。

        - pywhispercpp >= 1.5：``token_timestamps``
        - pywhispercpp <  1.5：``word_timestamps``
        """
        if self._ts_kwarg is not None:
            return self._ts_kwarg or None
        try:
            from pywhispercpp import model as _m  # noqa: F401
            import inspect
            src = inspect.getsource(_m)
            if "token_timestamps" in src:
                self._ts_kwarg = "token_timestamps"
            elif "word_timestamps" in src:
                self._ts_kwarg = "word_timestamps"
            else:
                self._ts_kwarg = ""
        except Exception:
            self._ts_kwarg = ""
        return self._ts_kwarg or None

    def _mock_result(
        self,
        audio_path: str,
        duration: float = 0.0,
    ) -> TranscriptResult:
        logger.warning("[whisper] using mock fallback for %s", audio_path)
        return TranscriptResult(
            text="",
            tokens=[],
            audio_duration_sec=duration,
            used_core_ml=False,
            model_id=self._model_name,
            language=self._language,
            fallback=True,
        )

    def _init(self) -> None:
        """首次 transcribe 时加载模型。"""
        try:
            from pywhispercpp.model import Model
            logger.info(
                "[whisper] loading model=%s core_ml=%s threads=%d",
                self._model_name, self._core_ml_enabled, self._n_threads,
            )
            self._model = Model(
                self._resolve_model_arg(),
                n_threads=self._n_threads,
                print_progress=False,
                print_realtime=False,
                print_timestamps=False,
            )
            logger.info("[whisper] model loaded ok")
        except Exception as exc:
            self._init_err = str(exc)
            logger.warning(
                "[whisper] model init failed (%s); will use mock fallback",
                exc,
            )
            self._model = None


@lru_cache(maxsize=1)
def get_whisper_service() -> WhisperService:
    """全局单例(读 .env 配置)。

    单例可避免每次 transcribe 都重新加载模型(模型小文件 ~466MB,
    加载耗时约 2-5 秒)。
    """
    from ielts_buddy.web import config as web_config

    return WhisperService(
        model=getattr(web_config, "WHISPER_MODEL", "small.en"),
        language=getattr(web_config, "WHISPER_LANGUAGE", "en"),
        core_ml=bool(getattr(web_config, "WHISPER_CORE_ML", True)),
        n_threads=int(getattr(web_config, "WHISPER_THREADS", "4") or "4"),
    )


__all__ = [
    "WhisperService",
    "TranscriptResult",
    "get_whisper_service",
]
