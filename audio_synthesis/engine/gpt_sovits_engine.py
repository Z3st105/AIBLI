#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPT-SoVITS TTS 引擎适配器
封装现有的 GPT-SoVITS 推理逻辑，实现统一的 TTS 接口
"""

import os
import sys
import re
import numpy as np
from typing import Optional, Generator

from engine.tts_engine_base import TTSEngineBase, TTSConfig, CharacterVoiceProfile

# GPT-SoVITS 引擎路径
GPT_SOVITS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "GPT_SoVITS")


class GPTSoVITSEngine(TTSEngineBase):
    """GPT-SoVITS TTS 引擎"""

    def __init__(self):
        self._infer = None
        self._loaded = False
        self._current_gpt = None
        self._current_sovits = None

    @property
    def engine_name(self) -> str:
        return "gpt_sovits"

    @property
    def sample_rate(self) -> int:
        return 32000

    def _get_infer(self):
        """延迟加载 inference_webui"""
        if self._infer is None:
            # 添加 GPT-SoVITS 到路径
            if GPT_SOVITS_ROOT not in sys.path:
                sys.path.insert(0, GPT_SOVITS_ROOT)
                os.chdir(GPT_SOVITS_ROOT)

            import torch
            from config import is_half
            import inference_webui as infer
            self._infer = infer
        return self._infer

    def load_model(self, model_path: str = None, **kwargs) -> None:
        """
        加载 GPT-SoVITS 模型（实际是延迟加载，每个角色切换时才真正加载）
        """
        infer = self._get_infer()
        self._loaded = True
        print("[GPTSoVITS] 引擎就绪（延迟加载模式）")

    def _ensure_character_model(self, character: CharacterVoiceProfile):
        """确保当前角色的模型已加载"""
        infer = self._get_infer()

        # 从 extra_params 获取权重路径
        extra = character.extra_params or {}
        gpt_path = extra.get("gpt_weights")
        sovits_path = extra.get("sovits_weights")

        if gpt_path and gpt_path != self._current_gpt:
            print(f"[GPTSoVITS] 切换 GPT 权重: {os.path.basename(gpt_path)}")
            infer.change_gpt_weights(gpt_path)
            self._current_gpt = gpt_path

        if sovits_path and sovits_path != self._current_sovits:
            print(f"[GPTSoVITS] 切换 SoVITS 权重: {os.path.basename(sovits_path)}")
            infer.change_sovits_weights(sovits_path)
            self._current_sovits = sovits_path

    def _split_text(self, text: str, min_chars: int = 10) -> list:
        """按标点切分长文本"""
        parts = re.split(r'([，。,.;；！？!?""''""]'' ""])', text)
        result = []
        current = ""
        for part in parts:
            current += part
            if part.strip() and part in "，。,.;；！？!?\"\"''\"\"''":
                if len(current.strip()) >= min_chars:
                    result.append(current.strip())
                    current = ""
        if current.strip():
            if result and len(current.strip()) < min_chars:
                result[-1] += current.strip()
            else:
                result.append(current.strip())
        return result if result else [text]

    def synthesize(
        self,
        text: str,
        voice_profile: CharacterVoiceProfile,
        config: TTSConfig,
    ) -> Optional[np.ndarray]:
        """合成单句音频"""
        if not self._loaded:
            print("[GPTSoVITS] 错误: 引擎未初始化")
            return None

        try:
            self._ensure_character_model(voice_profile)
            infer = self._get_infer()

            # 语言设置
            prompt_lang = voice_profile.ref_lang or "中文"
            text_lang = voice_profile.ref_lang or "中文"

            # 切分长文本
            segments = self._split_text(text)
            audio_segments = []
            zero_wav = np.zeros(int(self.sample_rate * config.pause_second), dtype=np.int16)

            for idx, seg_text in enumerate(segments):
                if not seg_text.strip():
                    continue

                seg_audio = []
                for result in infer.get_tts_wav(
                    ref_wav_path=voice_profile.ref_audio_path,
                    prompt_text=voice_profile.ref_text,
                    prompt_language=prompt_lang,
                    text=seg_text,
                    text_language=text_lang,
                    how_to_cut="不切",
                    top_k=config.top_k,
                    top_p=config.top_p,
                    temperature=config.temperature,
                    ref_free=False,
                    speed=config.speed,
                    if_freeze=False,
                    inp_refs=None,
                    sample_steps=8,
                    if_sr=False,
                    pause_second=config.pause_second,
                ):
                    if isinstance(result, tuple) and len(result) == 2:
                        sr, audio_int16 = result
                        seg_audio.append(audio_int16)

                if seg_audio:
                    audio_segments.append(np.concatenate(seg_audio))
                    if idx < len(segments) - 1:
                        audio_segments.append(zero_wav)

            if not audio_segments:
                return None

            return np.concatenate(audio_segments)

        except Exception as e:
            print(f"[GPTSoVITS] 合成失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def is_loaded(self) -> bool:
        return self._loaded

    def unload(self) -> None:
        """卸载引擎"""
        self._infer = None
        self._loaded = False
        self._current_gpt = None
        self._current_sovits = None
        print("[GPTSoVITS] 引擎已卸载")
