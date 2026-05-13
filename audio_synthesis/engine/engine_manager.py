#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TTS 引擎管理器
负责引擎的注册、选择、切换和配置
"""

import os
import json
from typing import Optional, Dict
from engine.tts_engine_base import TTSEngineBase, TTSConfig, CharacterVoiceProfile


class EngineManager:
    """TTS 引擎管理器"""

    def __init__(self, default_engine: str = "fish_speech"):
        """
        Args:
            default_engine: 默认使用的引擎 ("gpt_sovits" / "fish_speech")
        """
        self._engines: Dict[str, TTSEngineBase] = {}
        self._default_engine = default_engine
        self._current_engine: Optional[TTSEngineBase] = None

    def register_engine(self, engine: TTSEngineBase) -> None:
        """注册一个 TTS 引擎"""
        self._engines[engine.engine_name] = engine
        print(f"[EngineManager] 注册引擎: {engine.engine_name}")

    def get_engine(self, name: str) -> Optional[TTSEngineBase]:
        """获取指定名称的引擎"""
        return self._engines.get(name)

    def get_current_engine(self) -> Optional[TTSEngineBase]:
        """获取当前使用的引擎"""
        return self._current_engine

    def set_default_engine(self, name: str) -> bool:
        """设置默认引擎"""
        if name in self._engines:
            self._default_engine = name
            return True
        return False

    def load_engine(self, name: str, **kwargs) -> bool:
        """
        加载指定引擎的模型
        Args:
            name: 引擎名称
            **kwargs: 传递给引擎 load_model 的参数
        Returns:
            是否加载成功
        """
        engine = self._engines.get(name)
        if engine is None:
            print(f"[EngineManager] 错误: 引擎 '{name}' 未注册")
            return False

        try:
            engine.load_model(**kwargs)
            if self._current_engine is None:
                self._current_engine = engine
            return True
        except Exception as e:
            print(f"[EngineManager] 加载引擎 '{name}' 失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def select_engine_for_character(
        self,
        voice_profile: CharacterVoiceProfile,
        force_engine: Optional[str] = None,
    ) -> TTSEngineBase:
        """
        为角色选择合适的引擎
        优先级：force_engine > 角色偏好 > 默认引擎

        Args:
            voice_profile: 角色语音配置
            force_engine: 强制使用的引擎名称
        Returns:
            选择的引擎实例
        """
        # 1. 强制指定的引擎
        if force_engine and force_engine in self._engines:
            engine = self._engines[force_engine]
            if engine.is_loaded():
                return engine

        # 2. 角色偏好的引擎
        if voice_profile.engine_preference:
            engine = self._engines.get(voice_profile.engine_preference)
            if engine and engine.is_loaded():
                return engine

        # 3. 默认引擎
        engine = self._engines.get(self._default_engine)
        if engine and engine.is_loaded():
            return engine

        # 4. 任意已加载的引擎
        for engine in self._engines.values():
            if engine.is_loaded():
                return engine

        raise RuntimeError("[EngineManager] 没有可用的已加载引擎")

    def synthesize(
        self,
        text: str,
        voice_profile: CharacterVoiceProfile,
        config: TTSConfig,
        force_engine: Optional[str] = None,
    ):
        """
        使用合适的引擎合成音频
        Args:
            text: 要合成的文本
            voice_profile: 角色语音配置
            config: TTS 配置
            force_engine: 强制使用的引擎
        Returns:
            numpy array of audio samples, or None if failed
        """
        engine = self.select_engine_for_character(voice_profile, force_engine)
        return engine.synthesize(text, voice_profile, config)

    def list_engines(self) -> list:
        """列出所有注册的引擎及其状态"""
        result = []
        for name, engine in self._engines.items():
            result.append({
                "name": name,
                "loaded": engine.is_loaded(),
                "is_default": name == self._default_engine,
                "sample_rate": engine.sample_rate,
            })
        return result

    def unload_all(self) -> None:
        """卸载所有引擎"""
        for engine in self._engines.values():
            engine.unload()
        self._current_engine = None
        print("[EngineManager] 所有引擎已卸载")


def load_character_profiles(characters_dir: str) -> Dict[str, CharacterVoiceProfile]:
    """
    加载角色配置目录，返回 CharacterVoiceProfile 字典

    目录结构预期：
    characters_dir/
        角色名/
            profile.json
            ref_audio/  (*.wav / *.flac)
            ref_text.txt
            ref_lang.txt
            alias.txt
            engine_preference.txt  (可选: "gpt_sovits" / "fish_speech")
    """
    import glob

    characters = {}

    if not os.path.exists(characters_dir):
        print(f"[角色加载] 目录不存在: {characters_dir}")
        return characters

    for char_name in os.listdir(characters_dir):
        char_path = os.path.join(characters_dir, char_name)
        if not os.path.isdir(char_path):
            continue

        # 读取 profile.json
        profile_path = os.path.join(char_path, "profile.json")
        profile = {}
        if os.path.exists(profile_path):
            with open(profile_path, "r", encoding="utf-8") as f:
                profile = json.load(f)

        # 角色标识
        alias_path = os.path.join(char_path, "alias.txt")
        char_id = char_name
        if os.path.exists(alias_path):
            with open(alias_path, "r", encoding="utf-8") as f:
                char_id = f.read().strip().lstrip("\ufeff") or char_name

        # 参考音频
        ref_dir = os.path.join(char_path, "ref_audio")
        ref_audios = glob.glob(os.path.join(ref_dir, "*.wav")) + glob.glob(os.path.join(ref_dir, "*.flac"))
        ref_wav = ref_audios[0] if ref_audios else None

        # 参考文本
        ref_text_path = os.path.join(char_path, "ref_text.txt")
        ref_text = ""
        if os.path.exists(ref_text_path):
            with open(ref_text_path, "r", encoding="utf-8") as f:
                ref_text = f.read().strip().lstrip("\ufeff")

        # 参考语言
        ref_lang_path = os.path.join(char_path, "ref_lang.txt")
        ref_lang = profile.get("language", "中文")
        if os.path.exists(ref_lang_path):
            with open(ref_lang_path, "r", encoding="utf-8") as f:
                ref_lang = f.read().strip().lstrip("\ufeff") or ref_lang

        # 引擎偏好
        engine_pref_path = os.path.join(char_path, "engine_preference.txt")
        engine_pref = None
        if os.path.exists(engine_pref_path):
            with open(engine_pref_path, "r", encoding="utf-8") as f:
                engine_pref = f.read().strip().lstrip("\ufeff") or None

        # GPT-SoVITS 权重（如果有的话）
        extra_params = {}
        gpt_dir = os.path.join(char_path, "gpt_weights")
        if os.path.exists(gpt_dir):
            gpt_files = glob.glob(os.path.join(gpt_dir, "*.ckpt"))
            if gpt_files:
                extra_params["gpt_weights"] = max(gpt_files, key=os.path.getmtime)

        sovits_dir = os.path.join(char_path, "sovits_weights")
        if os.path.exists(sovits_dir):
            sovits_files = glob.glob(os.path.join(sovits_dir, "*.pth"))
            if sovits_files:
                extra_params["sovits_weights"] = max(sovits_files, key=os.path.getmtime)

        # 检查必要资产
        if not ref_wav:
            print(f"[角色加载] 警告: 角色 '{char_name}' 缺少参考音频，跳过")
            continue

        if not ref_text:
            print(f"[角色加载] 警告: 角色 '{char_name}' 缺少参考文本，跳过")
            continue

        characters[char_id] = CharacterVoiceProfile(
            char_id=char_id,
            name=char_name,
            ref_audio_path=ref_wav,
            ref_text=ref_text,
            ref_lang=ref_lang,
            engine_preference=engine_pref,
            extra_params=extra_params if extra_params else None,
        )
        print(f"[角色加载] {char_id} -> {char_name} (引擎偏好: {engine_pref or '默认'})")

    return characters
