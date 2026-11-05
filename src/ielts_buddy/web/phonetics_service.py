"""语音训练工坊 · 音标/拼读解析服务（v3.9 W11）。

PRD: docs/web-mvp/plans/phase-11-voice-training-prd.md §5.3

解析层级（设计文档 §5.3）：
1. CMUdict（pronouncing 库，确定性词表）→ ARPAbet → 美式 IPA
2. espeak-ng（phonemizer）兜底未收录词；缺失时该词 ipa=None 降级
3. 拼读规则说明：LLM 生成一次并按词文件缓存（第二次起零成本）
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from ielts_buddy.web.craft_rewrite_service import strip_reasoning

logger = logging.getLogger(__name__)

# ARPAbet → 美式 IPA（含重音标记处理）
_ARPABET_TO_IPA: dict[str, str] = {
    "AA": "ɑ", "AE": "æ", "AH": "ə", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "EH": "ɛ", "ER": "ɚ",
    "EY": "eɪ", "F": "f", "G": "ɡ", "HH": "h", "IH": "ɪ", "IY": "i",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ",
    "OW": "oʊ", "OY": "ɔɪ", "P": "p", "R": "r", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "UH": "ʊ", "UW": "u", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}

# 无教学价值的高频功能词（跳过拼读规则生成）
_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "in", "is", "it", "was", "i",
    "my", "me", "he", "she", "we", "they", "you", "that", "this", "on",
    "at", "for", "with", "as", "be", "are", "am", "do", "did", "so",
    "but", "or", "if", "not", "have", "has", "had", "will", "would",
}

_WORD_RE = re.compile(r"[A-Za-z']+")

# IPA 符号切分（元音/辅音/重音）
_IPA_SPLIT_RE = re.compile(r"(ˈ|ˌ)?([ɑæəɔaɛeɪɪioʊʊuʌɜɒæubdfɡhjklmnprstvwzʒθðŋʃtʃdʒw]+)")


def _arpabet_to_ipa(arpabet: str) -> str:
    """'S K EH1 JH UH0 L' → /ˈskɛdʒʊl/（美式）。

    CMUdict 把重音数字标在元音上；IPA 惯例是重音符号放在
    音节开头（元音前的辅音簇之前），因此遇到重读元音时把 ˈ/ˌ
    插到待输出辅音簇的最前面。
    """
    phones = arpabet.split()
    out: list[str] = []
    pending_cons: list[str] = []  # 待归属音节的辅音簇
    for p in phones:
        stress = 0
        if p and p[-1] in "012":
            stress = int(p[-1])
            p = p[:-1]
        ipa = _ARPABET_TO_IPA.get(p)
        if ipa is None:
            continue
        if p in _ARPABET_TO_IPA_VOWELS:
            prefix = ""
            if stress == 1:
                prefix = "ˈ"
            elif stress == 2:
                prefix = "ˌ"
            out.append(prefix + "".join(pending_cons) + ipa)
            pending_cons = []
        else:
            pending_cons.append(ipa)
    out.append("".join(pending_cons))
    s = "".join(out)
    return f"/{s}/" if s else ""


# ARPAbet 元音集合（重音判定用）
_ARPABET_TO_IPA_VOWELS = {
    "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY",
    "IH", "IY", "OW", "OY", "UH", "UW",
}


def _split_phonemes(ipa: str) -> list[str]:
    """把 /ˈskɛdʒuːlɪŋ/ 切成音素数组（含重音符号）。"""
    body = ipa.strip().strip("/")
    if not body:
        return []
    # 按 tʃ/dʒ 等双字符辅音与单字符切
    tokens: list[str] = []
    i = 0
    while i < len(body):
        two = body[i : i + 2]
        if two in ("tʃ", "dʒ"):
            tokens.append(two)
            i += 2
        elif body[i] in "ˈˌ":
            # 重音附着于下一个音素
            nxt = body[i + 1] if i + 1 < len(body) else ""
            if nxt:
                tokens.append(body[i] + nxt)
                i += 2
            else:
                i += 1
        else:
            tokens.append(body[i])
            i += 1
    return tokens


def _espeak_ipa(word: str, lang: str) -> Optional[str]:
    """phonemizer(espeak-ng) 兜底。返回 /ipa/；espeak 缺失返回 None。"""
    try:
        from phonemizer import phonemize
        out = phonemize(word, language=lang, backend="espeak",
                        strip=True, language_switch="remove-flags")
        out = (out or "").strip()
        if not out or not out.replace(" ", "").isascii() is False:
            pass  # espeak 可能返回多解，取第一个词
        first = out.split()[0] if out else ""
        if not first:
            return None
        return f"/{first}/"
    except Exception as exc:
        logger.debug("[phonetics] espeak 兜底失败(%s): %s", lang, exc)
        return None


class PhoneticsService:
    """逐词音标 + 音素 + 拼读规则。"""

    def __init__(self) -> None:
        self._rules_cache: Optional[Path] = None
        self._rules: dict[str, str] = {}
        self._load_rules()

    # ------------------------------------------------------------------
    # 缓存
    # ------------------------------------------------------------------

    @property
    def rules_path(self) -> Path:
        from ielts_buddy.web.voice_tts_service import get_voice_root
        return get_voice_root() / "word_rules.json"

    def _load_rules(self) -> None:
        try:
            if self.rules_path.exists():
                self._rules = json.loads(self.rules_path.read_text("utf-8"))
        except Exception:
            self._rules = {}

    def _save_rules(self) -> None:
        try:
            self.rules_path.write_text(
                json.dumps(self._rules, ensure_ascii=False, indent=0), "utf-8"
            )
        except Exception as exc:
            logger.warning("[phonetics] 规则缓存写入失败: %s", exc)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def parse_text(self, en_text: str) -> list[dict]:
        """整段解析：返回逐词 [{word, ipa_us, ipa_uk, phonemes}]。"""
        words = _WORD_RE.findall(en_text or "")
        seen: set[str] = set()
        out: list[dict] = []
        for w in words:
            key = w.lower().strip("'")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(self.parse_word(w))
        return out

    def parse_word(self, word: str) -> dict:
        """单词解析。CMUdict 优先，espeak 兜底，均失败 ipa=None。"""
        w = word.lower().strip("',.")
        result = {"word": word, "ipa_us": None, "ipa_uk": None, "phonemes": []}
        if not w:
            return result

        ipa_us: Optional[str] = None
        try:
            import pronouncing
            phones = pronouncing.phones_for_word(w)
            if phones:
                ipa_us = _arpabet_to_ipa(phones[0])
        except ImportError:
            logger.debug("[phonetics] pronouncing 未安装")
        except Exception as exc:
            logger.debug("[phonetics] CMUdict 查询失败: %s", exc)

        if ipa_us:
            result["ipa_us"] = ipa_us
            result["phonemes"] = _split_phonemes(ipa_us)
            # 英式取 espeak GB（缺失时留空降级）
            result["ipa_uk"] = _espeak_ipa(w, "en-gb") or ""
        else:
            us = _espeak_ipa(w, "en-us")
            uk = _espeak_ipa(w, "en-gb")
            if us:
                result["ipa_us"] = us
                result["phonemes"] = _split_phonemes(us)
            result["ipa_uk"] = uk or ""
        return result

    def word_rule(self, word: str) -> str:
        """拼读规则说明（LLM 生成一次 + 永久缓存）。停用词直接返回空串。"""
        w = word.lower().strip("',.")
        if not w or w in _STOPWORDS:
            return ""
        if w in self._rules:
            return self._rules[w]

        rule = self._llm_rule(w)
        if rule:
            self._rules[w] = rule
            self._save_rules()
        return rule

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _llm_rule(self, word: str) -> str:
        from ielts_buddy.web.llm_service import get_llm_service
        llm = get_llm_service()
        if not llm.is_available():
            return ""
        try:
            client = llm._ensure_client()
            resp = client.chat.completions.create(
                model=llm.model,
                messages=[
                    {"role": "system", "content": "You are an English phonetics coach."},
                    {"role": "user", "content": (
                        f'Explain the spelling-to-sound rule of the English word '
                        f'"{word}" in ONE short Chinese sentence (≤30字). '
                        f'Focus on which letter combination makes which sound, '
                        f'e.g. "ch 在词首读 /tʃ/"。Output only the sentence.'
                    )},
                ],
                temperature=0.3,
            )
            return strip_reasoning(resp.choices[0].message.content or "")
        except Exception as exc:
            logger.warning("[phonetics] LLM 规则生成失败(%s): %s", word, exc)
            return ""


# ---- 单例 ----
_phonetics_service: Optional[PhoneticsService] = None


def get_phonetics_service() -> PhoneticsService:
    global _phonetics_service
    if _phonetics_service is None:
        _phonetics_service = PhoneticsService()
    return _phonetics_service
