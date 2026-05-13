"""
AIBLI TTS 引擎模块
支持多引擎架构，包括 Fish Speech 和 GPT-SoVITS
"""

from .tts_engine_base import TTSEngineBase, TTSConfig, CharacterVoiceProfile
from .fish_speech_engine import FishSpeechEngine
from .gpt_sovits_engine import GPTSoVITSEngine
from .engine_manager import EngineManager, load_character_profiles

__all__ = [
    "TTSEngineBase",
    "TTSConfig",
    "CharacterVoiceProfile",
    "FishSpeechEngine",
    "GPTSoVITSEngine",
    "EngineManager",
    "load_character_profiles",
]
