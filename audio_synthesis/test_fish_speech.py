#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 Fish Speech 引擎集成
"""

import os
import sys
import numpy as np

# 添加当前目录到路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from engine.tts_engine_base import TTSConfig, CharacterVoiceProfile
from engine.fish_speech_engine import FishSpeechEngine


def test_fish_speech():
    """测试 Fish Speech 引擎"""
    print("=" * 60)
    print("测试 Fish Speech 引擎")
    print("=" * 60)

    # 创建引擎实例
    engine = FishSpeechEngine()

    # 检查初始状态
    print(f"\n1. 初始状态:")
    print(f"   引擎名称: {engine.engine_name}")
    print(f"   采样率: {engine.sample_rate}")
    print(f"   已加载: {engine.is_loaded()}")

    # 加载模型
    print(f"\n2. 加载模型...")
    try:
        engine.load_model()
        print(f"   加载成功: {engine.is_loaded()}")
    except Exception as e:
        print(f"   加载失败: {e}")
        import traceback
        traceback.print_exc()
        return

    # 创建测试角色配置
    # 注意：需要有参考音频才能测试
    test_ref_audio = os.path.join(BASE_DIR, "character_profile", "W", "ref_audio")
    ref_audios = []
    if os.path.exists(test_ref_audio):
        ref_audios = [f for f in os.listdir(test_ref_audio) if f.endswith(('.wav', '.flac'))]

    if not ref_audios:
        print("\n3. 跳过合成测试: 没有参考音频文件")
        print("   请先在 character_profile/W/ref_audio/ 放入参考音频文件")
        engine.unload()
        return

    ref_audio_path = os.path.join(test_ref_audio, ref_audios[0])
    voice_profile = CharacterVoiceProfile(
        char_id="test",
        name="测试角色",
        ref_audio_path=ref_audio_path,
        ref_text="这是一段测试文本",
        ref_lang="中文",
    )

    config = TTSConfig(
        top_k=20,
        top_p=0.6,
        temperature=0.6,
        speed=1.0,
        pause_second=0.3,
    )

    # 测试合成
    print(f"\n3. 测试合成:")
    print(f"   参考音频: {ref_audio_path}")
    print(f"   测试文本: 你好，这是Fish Speech引擎测试")

    try:
        audio = engine.synthesize(
            text="你好，这是Fish Speech引擎测试",
            voice_profile=voice_profile,
            config=config,
        )

        if audio is not None:
            print(f"   合成成功!")
            print(f"   音频形状: {audio.shape}")
            print(f"   音频类型: {audio.dtype}")
            print(f"   时长: {len(audio) / engine.sample_rate:.2f} 秒")

            # 保存测试音频
            import soundfile as sf
            test_output = os.path.join(BASE_DIR, "test_output.wav")
            sf.write(test_output, audio.astype(np.int16), engine.sample_rate)
            print(f"   已保存到: {test_output}")
        else:
            print(f"   合成失败: 返回 None")

    except Exception as e:
        print(f"   合成失败: {e}")
        import traceback
        traceback.print_exc()

    # 卸载引擎
    print(f"\n4. 卸载引擎...")
    engine.unload()
    print(f"   已卸载: {not engine.is_loaded()}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_fish_speech()
