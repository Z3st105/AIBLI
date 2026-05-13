#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频合成自动化链路 v2 - 多引擎版本
功能：读取多角色文案 -> 按角色调用 TTS 配音 -> 按顺序输出音频片段 + 序列日志

支持的 TTS 引擎：
    - Fish Speech 1.5 (默认)
    - GPT-SoVITS

用法：
    python audio_synthesis_pipeline_v2.py \
        --project P111 \
        --script "project_input/P111_script.txt" \
        --output_dir "project_output" \
        --engine fish_speech

文案格式（示例）：
    [A] 大家好，欢迎收看本期节目
    [B] 我是吐槽役，今天来吐槽一下
    [A] 首先我们来看看第一条新闻
"""

import os
import sys
import re
import json
import glob
import argparse
import traceback
import numpy as np
import soundfile as sf
from collections import defaultdict
from typing import Optional

# ==================== 路径配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHARACTER_DIR = os.path.join(BASE_DIR, "character_profile")
PROJECT_OUTPUT_DIR = os.path.join(BASE_DIR, "project_output")

# 引入引擎模块
sys.path.insert(0, BASE_DIR)

from engine.tts_engine_base import TTSConfig, CharacterVoiceProfile
from engine.engine_manager import EngineManager, load_character_profiles


def log(msg):
    try:
        print(f"[AudioSynth] {msg}")
    except UnicodeEncodeError:
        out = f"[AudioSynth] {msg}\n"
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))


# ==================== 引擎初始化 ====================

def create_engine_manager(engine_name: str = "fish_speech", **kwargs) -> EngineManager:
    """
    创建并初始化引擎管理器
    Args:
        engine_name: 要加载的引擎 ("fish_speech" / "gpt_sovits" / "all")
        **kwargs: 传递给引擎的参数
    Returns:
        EngineManager 实例
    """
    manager = EngineManager(default_engine=engine_name)

    # 注册 Fish Speech 引擎
    from engine.fish_speech_engine import FishSpeechEngine
    fish_engine = FishSpeechEngine()
    manager.register_engine(fish_engine)

    # 注册 GPT-SoVITS 引擎
    from engine.gpt_sovits_engine import GPTSoVITSEngine
    gpt_engine = GPTSoVITSEngine()
    manager.register_engine(gpt_engine)

    # 加载指定引擎
    if engine_name == "all":
        # 加载所有引擎
        manager.load_engine("fish_speech", **kwargs)
        manager.load_engine("gpt_sovits", **kwargs)
    elif engine_name == "fish_speech":
        manager.load_engine("fish_speech", **kwargs)
    elif engine_name == "gpt_sovits":
        manager.load_engine("gpt_sovits", **kwargs)
    else:
        log(f"[错误] 未知引擎: {engine_name}")
        sys.exit(1)

    return manager


# ==================== 文案解析 ====================

def parse_script(script_path):
    """
    解析文案文件，支持格式：
        [角色标识] 台词内容
        [角色标识-语言] 台词内容   如 [A-ja]、[B-zh]
        [角色标识@引擎] 台词内容   如 [A@fish_speech]、[B@gpt_sovits]
    返回: [(角色标识, 台词文本, 语言, 引擎), ...]
    """
    lines = []
    with open(script_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            # 匹配 [角色-语言@引擎] 台词  或  [角色] 台词
            m = re.match(r'^\[([^\]]+?)\]\s*(.+)$', raw)
            if m:
                header, text = m.groups()
                header = header.strip()

                char_id = header
                lang = None
                engine = None

                # 检查是否有引擎标注
                if "@" in header:
                    parts = header.rsplit("@", 1)
                    char_id = parts[0].strip()
                    engine = parts[1].strip()

                # 检查是否有语言标注
                if "-" in char_id:
                    char_id, lang = char_id.rsplit("-", 1)
                    char_id = char_id.strip()
                    lang = lang.strip()

                lines.append((char_id, text.strip(), lang, engine))
            else:
                log(f"[解析警告] 无法解析的行: {raw[:50]}")
    return lines


def split_text_by_punctuation(text, min_chars=10):
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


# ==================== 项目执行 ====================

def run_project(project_name, script_path, output_root=None,
                engine_name="fish_speech", force_engine=None,
                top_k=20, top_p=0.6, temperature=0.6,
                speed=1.0, pause_second=0.3):
    """
    执行一个项目的完整配音流程
    """
    output_root = output_root or PROJECT_OUTPUT_DIR
    project_dir = os.path.join(output_root, project_name)
    os.makedirs(project_dir, exist_ok=True)

    log("=" * 60)
    log(f"开始项目: {project_name}")
    log(f"文案: {script_path}")
    log(f"输出: {project_dir}")
    log(f"引擎: {engine_name}")
    log("=" * 60)

    # 初始化引擎
    log("[初始化] 加载 TTS 引擎...")
    manager = create_engine_manager(engine_name)

    # 显示引擎状态
    for info in manager.list_engines():
        status = "已加载" if info["loaded"] else "未加载"
        default = " [默认]" if info["is_default"] else ""
        log(f"  - {info['name']}: {status} (采样率: {info['sample_rate']}){default}")

    # 加载角色
    log("[初始化] 加载角色配置...")
    characters = load_character_profiles(CHARACTER_DIR)
    if not characters:
        log("[错误] 没有可用角色，请检查 character_profile/ 目录")
        return

    # TTS 配置
    tts_config = TTSConfig(
        top_k=top_k,
        top_p=top_p,
        temperature=temperature,
        speed=speed,
        pause_second=pause_second,
    )

    # 解析文案
    lines = parse_script(script_path)
    if not lines:
        log("[错误] 文案解析结果为空")
        return

    log(f"[文案] 共 {len(lines)} 句台词")

    # 统计角色出现次序
    sequence_by_char = defaultdict(list)
    dialogue_order = []

    # 逐句生成
    current_char = None
    current_engine_name = None

    for idx, (char_id, text, text_lang_override, line_engine) in enumerate(lines, start=1):
        if char_id not in characters:
            log(f"[错误] 角色 '{char_id}' 未找到，跳过第 {idx} 句")
            continue

        char = characters[char_id]
        seq_str = f"{idx:03d}"
        out_name = f"{seq_str}.wav"
        out_path = os.path.join(project_dir, out_name)

        log(f"[{seq_str}/{len(lines)}] {char_id}: {text[:40]}...")

        # 确定使用的引擎
        effective_engine = line_engine or force_engine

        # 切换角色时的提示
        if current_char != char_id:
            log(f"[切换角色] -> {char_id} ({char.name})")
            current_char = char_id

        try:
            # 使用引擎管理器合成
            audio = manager.synthesize(
                text=text,
                voice_profile=char,
                config=tts_config,
                force_engine=effective_engine,
            )

            if audio is not None:
                # 保存音频
                sf.write(out_path, audio.astype(np.int16), 32000)
                sequence_by_char[char_id].append(idx)
                dialogue_order.append({
                    "seq": seq_str,
                    "char": char_id,
                    "text": text,
                    "lang": text_lang_override or char.ref_lang,
                    "engine": effective_engine or engine_name,
                })
                log(f"[成功] 已保存: {out_name}")
            else:
                log(f"[错误] 第 {idx} 句生成失败: 返回空音频")
                dialogue_order.append({
                    "seq": seq_str,
                    "char": char_id,
                    "text": text,
                    "lang": text_lang_override or char.ref_lang,
                    "engine": effective_engine or engine_name,
                    "error": True,
                })

        except Exception as e:
            log(f"[错误] 第 {idx} 句生成失败: {e}")
            traceback.print_exc()
            dialogue_order.append({
                "seq": seq_str,
                "char": char_id,
                "text": text,
                "lang": text_lang_override or char.ref_lang,
                "engine": effective_engine or engine_name,
                "error": True,
            })

    # ==================== 生成日志 ====================

    # 1. sequence_log.txt
    seq_log_path = os.path.join(project_dir, "sequence_log.txt")
    with open(seq_log_path, "w", encoding="utf-8") as f:
        f.write(f"# 项目: {project_name}\n")
        f.write(f"# 总句数: {len(lines)}\n")
        f.write(f"# 使用引擎: {engine_name}\n")
        f.write("# 角色出现次序\n")
        f.write("-" * 40 + "\n")
        for char_id in sorted(sequence_by_char.keys()):
            seqs = sequence_by_char[char_id]
            f.write(f"{char_id}: {', '.join(map(str, seqs))}\n")
        f.write("-" * 40 + "\n")
        order_str = "".join([d["char"] for d in dialogue_order])
        f.write(f"说话顺序: {order_str}\n")
    log(f"[日志] sequence_log.txt 已生成")

    # 2. manifest.json
    manifest = {
        "project": project_name,
        "total_lines": len(lines),
        "engine": engine_name,
        "dialogue": dialogue_order,
        "character_sequences": {
            char_id: seqs for char_id, seqs in sequence_by_char.items()
        }
    }
    manifest_path = os.path.join(project_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    log(f"[日志] manifest.json 已生成")

    # 3. dialogue_order.txt
    order_path = os.path.join(project_dir, "dialogue_order.txt")
    with open(order_path, "w", encoding="utf-8") as f:
        for d in dialogue_order:
            flag = "[ERR]" if d.get("error") else "[OK]"
            f.write(f"{d['seq']} {flag} [{d['char']}] {d['text']}\n")
    log(f"[日志] dialogue_order.txt 已生成")

    # ==================== 音频拼接 & 时间轴生成 ====================
    timeline = merge_project_audio(project_dir, dialogue_order, pause_second)

    # 4. timeline.json
    if timeline:
        timeline_data = {
            "project": project_name,
            "merged_audio": "merged.wav",
            "total_duration_sec": round(timeline[-1]["end_sec"], 2) if timeline else 0,
            "pause_between_clips_sec": pause_second,
            "segments": timeline,
        }
        timeline_path = os.path.join(project_dir, "timeline.json")
        with open(timeline_path, "w", encoding="utf-8") as f:
            json.dump(timeline_data, f, ensure_ascii=False, indent=2)
        log(f"[日志] timeline.json 已生成")

    # 卸载引擎
    manager.unload_all()

    log("=" * 60)
    log(f"项目完成: {project_dir}")
    log("=" * 60)


def merge_project_audio(project_dir, dialogue_order, pause_second=0.3):
    """拼接所有音频片段"""
    wav_files = sorted(glob.glob(os.path.join(project_dir, "[0-9][0-9][0-9].wav")))
    if not wav_files:
        log("[拼接] 未找到可拼接的音频片段")
        return []

    dialogue_map = {d["seq"]: d for d in dialogue_order}
    segments = []
    sr = 32000
    pause_samples = int(sr * pause_second)
    zero_wav = np.zeros(pause_samples, dtype=np.int16)
    timeline = []
    current_time = 0.0

    for idx, wav_path in enumerate(wav_files):
        basename = os.path.basename(wav_path)
        seq = os.path.splitext(basename)[0]
        try:
            data, file_sr = sf.read(wav_path, dtype="int16")
            if file_sr != sr:
                log(f"[拼接警告] {basename} 采样率 {file_sr} != {sr}，跳过")
                continue

            duration = len(data) / sr
            info = dialogue_map.get(seq, {})
            timeline.append({
                "seq": seq,
                "char": info.get("char", "?"),
                "text": info.get("text", ""),
                "lang": info.get("lang", ""),
                "file": basename,
                "start_sec": round(current_time, 3),
                "end_sec": round(current_time + duration, 3),
                "duration_sec": round(duration, 3),
            })
            current_time += duration
            segments.append(data)
            if idx < len(wav_files) - 1:
                segments.append(zero_wav)
                current_time += pause_second
        except Exception as e:
            log(f"[拼接警告] 读取 {basename} 失败: {e}")

    if not segments:
        return []

    merged = np.concatenate(segments)
    out_path = os.path.join(project_dir, "merged.wav")
    sf.write(out_path, merged, sr)
    log(f"[拼接] 已生成合并音频: {out_path} ({len(timeline)} 个片段, 总时长 {len(merged)/sr:.1f}s)")
    return timeline


# ==================== 主入口 ====================

def main():
    parser = argparse.ArgumentParser(description="音频合成自动化链路 v2 (多引擎)")
    parser.add_argument("--project", required=True, help="项目编号/名称，如 P111")
    parser.add_argument("--script", required=True, help="文案文件路径")
    parser.add_argument("--output_dir", default=PROJECT_OUTPUT_DIR, help="输出根目录")
    parser.add_argument("--engine", default="fish_speech", choices=["fish_speech", "gpt_sovits", "all"],
                        help="使用的 TTS 引擎 (默认: fish_speech)")
    parser.add_argument("--force_engine", default=None, choices=["fish_speech", "gpt_sovits"],
                        help="强制所有句子使用指定引擎（覆盖角色偏好和文案标注）")
    parser.add_argument("--top_k", type=int, default=20)
    parser.add_argument("--top_p", type=float, default=0.6)
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--pause", type=float, default=0.3, help="段落间停顿秒数")
    args = parser.parse_args()

    run_project(
        project_name=args.project,
        script_path=args.script,
        output_root=args.output_dir,
        engine_name=args.engine,
        force_engine=args.force_engine,
        top_k=args.top_k,
        top_p=args.top_p,
        temperature=args.temperature,
        speed=args.speed,
        pause_second=args.pause,
    )


if __name__ == "__main__":
    main()
