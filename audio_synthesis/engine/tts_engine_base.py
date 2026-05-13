#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS 引擎抽象基类
所有 TTS 引擎（GPT-SoVITS、Fish Speech 等）都继承此基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Generator
import numpy as np


@dataclass
class TTSConfig:
    """TTS 推理配置"""
    top_k: int = 20
    top_p: float = 0.6
    temperature: float = 0.6
    speed: float = 1.0
    pause_second: float = 0.3
    sample_rate: int = 32000


@dataclass
class CharacterVoiceProfile:
    """角色语音配置"""
    char_id: str
    name: str
    ref_audio_path: str  # 参考音频路径
    ref_text: str         # 参考文本
    ref_lang: str = "中文"  # 参考音频语言
    engine_preference: Optional[str] = None  # 角色偏好的引擎 ("gpt_sovits" / "fish_speech" / None=用默认)
    extra_params: Optional[dict] = None  # 引擎特定的额外参数


class TTSEngineBase(ABC):
    """TTS 引擎基类"""

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """引擎名称，如 'gpt_sovits', 'fish_speech'"""
        pass

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """输出音频采样率"""
        pass

    @abstractmethod
    def load_model(self, model_path: str, **kwargs) -> None:
        """
        加载模型
        Args:
            model_path: 模型路径或标识
            **kwargs: 引擎特定参数
        """
        pass

    @abstractmethod
    def synthesize(
        self,
        text: str,
        voice_profile: CharacterVoiceProfile,
        config: TTSConfig,
    ) -> Optional[np.ndarray]:
        """
        合成单句音频
        Args:
            text: 要合成的文本
            voice_profile: 角色语音配置
            config: TTS 推理配置
        Returns:
            numpy array of audio samples (int16), or None if failed
        """
        pass

    def synthesize_streaming(
        self,
        text: str,
        voice_profile: CharacterVoiceProfile,
        config: TTSConfig,
    ) -> Generator[np.ndarray, None, None]:
        """
        流式合成（可选实现）
        默认实现：直接调用 synthesize 然后 yield 整段
        子类可以覆盖以实现真正的流式输出
        """
        audio = self.synthesize(text, voice_profile, config)
        if audio is not None:
            yield audio

    @abstractmethod
    def is_loaded(self) -> bool:
        """检查模型是否已加载"""
        pass

    def unload(self) -> None:
        """卸载模型，释放资源（可选实现）"""
        pass
