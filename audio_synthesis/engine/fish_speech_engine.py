#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fish Speech TTS 引擎适配器
封装 Fish Speech 1.5 推理引擎，实现统一的 TTS 接口
"""

import os
import sys
import queue
import numpy as np
import torch
from typing import Optional, Generator
from pathlib import Path

# Fish Speech 项目路径
FISH_SPEECH_ROOT = r"D:\fish-speech"

# 添加 Fish Speech 到 Python 路径
if FISH_SPEECH_ROOT not in sys.path:
    sys.path.insert(0, FISH_SPEECH_ROOT)

from engine.tts_engine_base import TTSEngineBase, TTSConfig, CharacterVoiceProfile


class FishSpeechEngine(TTSEngineBase):
    """Fish Speech TTS 引擎"""

    def __init__(self):
        self._llama_queue = None
        self._decoder_model = None
        self._inference_engine = None
        self._device = "cuda"
        self._precision = torch.bfloat16
        self._loaded = False

    @property
    def engine_name(self) -> str:
        return "fish_speech"

    @property
    def sample_rate(self) -> int:
        # Fish Speech 1.5 默认采样率
        return 44100

    def load_model(
        self,
        model_path: str = None,
        device: str = "cuda",
        half: bool = False,
        compile: bool = False,
        **kwargs
    ) -> None:
        """
        加载 Fish Speech 模型
        Args:
            model_path: 模型路径，默认为 checkpoints/fish-speech-1.5
            device: 推理设备 (cuda/cpu/mps)
            half: 是否使用半精度
            compile: 是否编译模型
        """
        import pyrootutils
        pyrootutils.setup_root(FISH_SPEECH_ROOT, indicator=".project-root", pythonpath=True)

        from fish_speech.inference_engine import TTSInferenceEngine
        from fish_speech.models.dac.inference import load_model as load_decoder_model
        from fish_speech.models.text2semantic.inference import launch_thread_safe_queue

        # 设置设备
        self._device = device
        if torch.backends.mps.is_available():
            self._device = "mps"
        elif torch.xpu.is_available():
            self._device = "xpu"
        elif not torch.cuda.is_available():
            self._device = "cpu"

        # 设置精度
        self._precision = torch.half if half else torch.bfloat16

        # 模型路径
        if model_path is None:
            model_path = os.path.join(FISH_SPEECH_ROOT, "checkpoints", "fish-speech-1.5")

        llama_checkpoint_path = Path(model_path)
        decoder_checkpoint_path = Path(os.path.join(model_path, "firefly-gan-vq-fsq-8x1024-21hz-generator.pth"))

        print(f"[FishSpeech] 加载 Llama 模型: {llama_checkpoint_path}")
        self._llama_queue = launch_thread_safe_queue(
            checkpoint_path=llama_checkpoint_path,
            device=self._device,
            precision=self._precision,
            compile=compile,
        )

        print(f"[FishSpeech] 加载 VQ-GAN 解码器: {decoder_checkpoint_path}")
        self._decoder_model = load_decoder_model(
            config_name="firefly_gan_vq",
            checkpoint_path=decoder_checkpoint_path,
            device=self._device,
        )

        # 创建推理引擎
        self._inference_engine = TTSInferenceEngine(
            llama_queue=self._llama_queue,
            decoder_model=self._decoder_model,
            compile=compile,
            precision=self._precision,
        )

        self._loaded = True
        print("[FishSpeech] 模型加载完成")

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
        if not self._loaded:
            print("[FishSpeech] 错误: 模型未加载")
            return None

        from fish_speech.utils.schema import ServeTTSRequest, ServeReferenceAudio

        # 读取参考音频
        ref_audio_bytes = None
        if voice_profile.ref_audio_path and os.path.exists(voice_profile.ref_audio_path):
            with open(voice_profile.ref_audio_path, "rb") as f:
                ref_audio_bytes = f.read()

        # 构建参考音频列表
        references = []
        if ref_audio_bytes and voice_profile.ref_text:
            references.append(ServeReferenceAudio(
                audio=ref_audio_bytes,
                text=voice_profile.ref_text,
            ))

        # 构建请求
        request = ServeTTSRequest(
            text=text,
            references=references,
            reference_id=None,
            max_new_tokens=1024,
            chunk_length=200,
            top_p=config.top_p,
            repetition_penalty=1.1,
            temperature=config.temperature,
            format="wav",
        )

        # 执行推理
        try:
            audio_segments = []
            for result in self._inference_engine.inference(request):
                if result.code == "final" and result.audio is not None:
                    sr, audio_data = result.audio
                    # 转换为 int16
                    if audio_data.dtype != np.int16:
                        audio_int16 = (audio_data * 32767).astype(np.int16)
                    else:
                        audio_int16 = audio_data
                    return audio_int16
                elif result.code == "error":
                    print(f"[FishSpeech] 推理错误: {result.error}")
                    return None

            return None
        except Exception as e:
            print(f"[FishSpeech] 合成失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def synthesize_streaming(
        self,
        text: str,
        voice_profile: CharacterVoiceProfile,
        config: TTSConfig,
    ) -> Generator[np.ndarray, None, None]:
        """流式合成"""
        if not self._loaded:
            print("[FishSpeech] 错误: 模型未加载")
            return

        from fish_speech.utils.schema import ServeTTSRequest, ServeReferenceAudio

        # 读取参考音频
        ref_audio_bytes = None
        if voice_profile.ref_audio_path and os.path.exists(voice_profile.ref_audio_path):
            with open(voice_profile.ref_audio_path, "rb") as f:
                ref_audio_bytes = f.read()

        references = []
        if ref_audio_bytes and voice_profile.ref_text:
            references.append(ServeReferenceAudio(
                audio=ref_audio_bytes,
                text=voice_profile.ref_text,
            ))

        request = ServeTTSRequest(
            text=text,
            references=references,
            reference_id=None,
            max_new_tokens=1024,
            chunk_length=200,
            top_p=config.top_p,
            repetition_penalty=1.1,
            temperature=config.temperature,
            format="wav",
            streaming=True,
        )

        try:
            for result in self._inference_engine.inference(request):
                if result.audio is not None:
                    sr, audio_data = result.audio
                    if audio_data.dtype != np.int16:
                        audio_int16 = (audio_data * 32767).astype(np.int16)
                    else:
                        audio_int16 = audio_data
                    yield audio_int16
        except Exception as e:
            print(f"[FishSpeech] 流式合成失败: {e}")
            import traceback
            traceback.print_exc()

    def is_loaded(self) -> bool:
        return self._loaded

    def unload(self) -> None:
        """卸载模型，释放资源"""
        self._llama_queue = None
        self._decoder_model = None
        self._inference_engine = None
        self._loaded = False
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("[FishSpeech] 模型已卸载")
