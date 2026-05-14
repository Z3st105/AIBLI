#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频合成自动化链路
功能：读取多角色文案 -> 按角色调用 GPT-SoVITS 配音 -> 按顺序输出音频片段 + 序列日志

用法：
    python audio_synthesis_pipeline.py \
        --project P111 \
        --script "project_input/P111_script.txt" \
        --output_dir "project_output"

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

# ==================== 路径配置 ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHARACTER_DIR = os.path.join(BASE_DIR, "character_profile")
PROJECT_OUTPUT_DIR = os.path.join(BASE_DIR, "project_output")

# 引入 GPT-SoVITS 原项目
GPT_SOVITS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine")
sys.path.insert(0, GPT_SOVITS_ROOT)
os.chdir(GPT_SOVITS_ROOT)

import torch
from config import is_half

# 延迟加载 inference_webui，避免初始化过早
g_infer = None

def get_infer():
    global g_infer
    if g_infer is None:
        import inference_webui as infer
        g_infer = infer
    return g_infer


def log(msg):
    try:
        print(f"[AudioSynth] {msg}")
    except UnicodeEncodeError:
        # Windows 控制台 GBK 编码兼容
        out = f"[AudioSynth] {msg}\n"
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))


# ==================== 角色管理 ====================

def load_characters():
    """
    扫描 character_profile/ 下的所有角色
    每个角色文件夹内应有：
        - gpt_weights/   (*.ckpt)
        - sovits_weights/ (*.pth)
        - ref_audio/     (*.wav / *.flac)
        - ref_text.txt
    返回: {角色标识: {gpt, sovits, ref_wav, ref_text, name}}
    """
    characters = {}
    if not os.path.exists(CHARACTER_DIR):
        log(f"角色目录不存在: {CHARACTER_DIR}")
        return characters

    for char_name in os.listdir(CHARACTER_DIR):
        char_path = os.path.join(CHARACTER_DIR, char_name)
        if not os.path.isdir(char_path):
            continue

        # GPT 权重
        gpt_dir = os.path.join(char_path, "gpt_weights")
        gpt_files = glob.glob(os.path.join(gpt_dir, "*.ckpt"))
        gpt_file = max(gpt_files, key=os.path.getmtime) if gpt_files else None

        # SoVITS 权重
        sovits_dir = os.path.join(char_path, "sovits_weights")
        sovits_files = glob.glob(os.path.join(sovits_dir, "*.pth"))
        sovits_file = max(sovits_files, key=os.path.getmtime) if sovits_files else None

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

        # 参考音频语言
        ref_lang_path = os.path.join(char_path, "ref_lang.txt")
        ref_lang = "中文"
        if os.path.exists(ref_lang_path):
            with open(ref_lang_path, "r", encoding="utf-8") as f:
                ref_lang = f.read().strip().lstrip("\ufeff") or "中文"

        if not all([gpt_file, sovits_file, ref_wav, ref_text]):
            log(f"[警告] 角色 '{char_name}' 资产不完整，跳过 (gpt:{bool(gpt_file)} sovits:{bool(sovits_file)} ref_wav:{bool(ref_wav)} ref_text:{bool(ref_text)})")
            continue

        # 角色标识默认取文件夹名，也可在文件夹内放 alias.txt 自定义
        alias_path = os.path.join(char_path, "alias.txt")
        char_id = char_name
        if os.path.exists(alias_path):
            with open(alias_path, "r", encoding="utf-8") as f:
                char_id = f.read().strip().lstrip("\ufeff") or char_name

        characters[char_id] = {
            "name": char_name,
            "gpt": gpt_file,
            "sovits": sovits_file,
            "ref_wav": ref_wav,
            "ref_text": ref_text,
            "ref_lang": ref_lang,
        }
        log(f"[角色加载] {char_id} -> {char_name}")

    return characters


# ==================== 文案解析 ====================

def parse_script(script_path):
    """
    解析文案文件，支持格式：
        [角色标识] 台词内容
        [角色标识-语言] 台词内容   如 [A-ja]、[B-zh]
    返回: [(角色标识, 台词文本, 语言), ...]
    语言可省略，默认使用角色的 ref_lang
    """
    lines = []
    with open(script_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            # 匹配 [角色-语言] 台词  或  [角色] 台词
            m = re.match(r'^\[([^\]]+?)\]\s*(.+)$', raw)
            if m:
                header, text = m.groups()
                header = header.strip()
                # 检查是否有语言标注
                if "-" in header:
                    char_id, lang = header.rsplit("-", 1)
                    char_id = char_id.strip()
                    lang = lang.strip()
                else:
                    char_id = header
                    lang = None  # 使用角色默认语言
                lines.append((char_id, text.strip(), lang))
            else:
                # 不匹配格式的行，尝试作为延续或跳过
                log(f"[解析警告] 无法解析的行: {raw[:50]}")
    return lines


def split_text_by_punctuation(text, min_chars=10):
    """按标点切分长文本，防止爆显存；同时避免片段过短导致生成质量差"""
    parts = re.split(r'([，。,.;；！？!?""''“”‘’])', text)
    result = []
    current = ""
    for part in parts:
        current += part
        if part.strip() and part in "，。,.;；！？!?\"\"''\"\"''":
            # 如果累积长度已达最小要求，就切分；否则继续累积
            if len(current.strip()) >= min_chars:
                result.append(current.strip())
                current = ""
    if current.strip():
        # 剩余文本太短，合并到最后一个片段（如果有）
        if result and len(current.strip()) < min_chars:
            result[-1] += current.strip()
        else:
            result.append(current.strip())
    return result if result else [text]


# ==================== TTS 推理 ====================

def synthesize_line(character, text, out_path,
                    top_k=20, top_p=0.6, temperature=0.6,
                    speed=1.0, pause_second=0.3,
                    text_lang="中文"):
    """
    为单句台词生成音频
    长文本自动按标点切分后逐段推理并拼接
    """
    infer = get_infer()

    # 加载模型（每个角色只需加载一次，外部已做缓存）
    infer.change_gpt_weights(character["gpt"])
    infer.change_sovits_weights(character["sovits"])

    # inference_webui 的 dict_language 键是 i18n 后的语种名，中文环境下为 "中文"
    prompt_lang_key = character.get("ref_lang", "中文")
    text_lang_key = text_lang

    segments = split_text_by_punctuation(text)
    audio_segments = []
    sr = 32000
    zero_wav = np.zeros(int(sr * pause_second), dtype=np.int16)

    for idx, seg_text in enumerate(segments):
        if not seg_text.strip():
            continue
        seg_audio = []
        for result in infer.get_tts_wav(
            ref_wav_path=character["ref_wav"],
            prompt_text=character["ref_text"],
            prompt_language=prompt_lang_key,
            text=seg_text,
            text_language=text_lang_key,
            how_to_cut="不切",
            top_k=top_k,
            top_p=top_p,
            temperature=temperature,
            ref_free=False,
            speed=speed,
            if_freeze=False,
            inp_refs=None,
            sample_steps=8,
            if_sr=False,
            pause_second=pause_second,
        ):
            if isinstance(result, tuple) and len(result) == 2:
                sr, audio_int16 = result
                seg_audio.append(audio_int16)

        if seg_audio:
            audio_segments.append(np.concatenate(seg_audio))
            if idx < len(segments) - 1:
                audio_segments.append(zero_wav)
        else:
            log(f"[警告] 段落 {idx+1} 未生成音频: {seg_text[:30]}")

    if not audio_segments:
        log(f"[错误] 整句未生成音频: {text[:50]}")
        return False

    full_audio = np.concatenate(audio_segments)
    sf.write(out_path, full_audio.astype(np.int16), sr)
    return True


# ==================== 项目执行 ====================

def run_project(project_name, script_path, output_root=None,
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
    log("=" * 60)

    # 加载角色
    characters = load_characters()
    if not characters:
        log("[错误] 没有可用角色，请检查 character_profile/ 目录")
        return

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
    for idx, (char_id, text, text_lang_override) in enumerate(lines, start=1):
        if char_id not in characters:
            log(f"[错误] 角色 '{char_id}' 未找到，跳过第 {idx} 句")
            continue

        char = characters[char_id]
        seq_str = f"{idx:03d}"
        out_name = f"{seq_str}.wav"
        out_path = os.path.join(project_dir, out_name)

        log(f"[{seq_str}/{len(lines)}] {char_id}: {text[:40]}...")

        # 只有切换角色时才重新加载权重（同角色连续台词复用）
        if current_char != char_id:
            log(f"[切换模型] -> {char_id} ({char['name']})")
            current_char = char_id

        try:
            # 确定目标语言：文案标注 > 角色默认 ref_lang
            text_lang = text_lang_override if text_lang_override else char.get("ref_lang", "中文")
            ok = synthesize_line(
                char, text, out_path,
                top_k=top_k, top_p=top_p, temperature=temperature,
                speed=speed, pause_second=pause_second,
                text_lang=text_lang
            )
        except Exception as e:
            log(f"[错误] 第 {idx} 句生成失败: {e}")
            traceback.print_exc()
            ok = False

        if ok:
            sequence_by_char[char_id].append(idx)
            dialogue_order.append({"seq": seq_str, "char": char_id, "text": text, "lang": text_lang})
        else:
            dialogue_order.append({"seq": seq_str, "char": char_id, "text": text, "lang": text_lang, "error": True})

    # ==================== 生成日志 ====================

    # 1. sequence_log.txt: 每个角色的出现序号
    seq_log_path = os.path.join(project_dir, "sequence_log.txt")
    with open(seq_log_path, "w", encoding="utf-8") as f:
        f.write(f"# 项目: {project_name}\n")
        f.write(f"# 总句数: {len(lines)}\n")
        f.write("# 角色出现次序\n")
        f.write("-" * 40 + "\n")
        for char_id in sorted(sequence_by_char.keys()):
            seqs = sequence_by_char[char_id]
            f.write(f"{char_id}: {', '.join(map(str, seqs))}\n")
        f.write("-" * 40 + "\n")
        # 说话顺序总览
        order_str = "".join([d["char"] for d in dialogue_order])
        f.write(f"说话顺序: {order_str}\n")
    log(f"[日志] sequence_log.txt 已生成")

    # 2. manifest.json: 详细清单
    manifest = {
        "project": project_name,
        "total_lines": len(lines),
        "dialogue": dialogue_order,
        "character_sequences": {
            char_id: seqs for char_id, seqs in sequence_by_char.items()
        }
    }
    manifest_path = os.path.join(project_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    log(f"[日志] manifest.json 已生成")

    # 3. dialogue_order.txt: 纯文本版顺序表（方便视频合成读取）
    order_path = os.path.join(project_dir, "dialogue_order.txt")
    with open(order_path, "w", encoding="utf-8") as f:
        for d in dialogue_order:
            flag = "[ERR]" if d.get("error") else "[OK]"
            f.write(f"{d['seq']} {flag} [{d['char']}] {d['text']}\n")
    log(f"[日志] dialogue_order.txt 已生成")

    # ==================== 音频拼接 & 时间轴生成 ====================
    timeline = merge_project_audio(project_dir, dialogue_order, pause_second)

    # 4. timeline.json: 带时间戳的编辑清单（发给视频后期部门）
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
        log(f"[日志] timeline.json 已生成（含时间轴，可直接发给视频部门）")

    log("=" * 60)
    log(f"项目完成: {project_dir}")
    log("=" * 60)


def merge_project_audio(project_dir, dialogue_order, pause_second=0.3):
    """
    把项目目录下所有 001.wav, 002.wav... 按顺序拼接成 merged.wav
    同时返回每段的时间轴信息 [(seq, char, text, start, end, file), ...]
    """
    wav_files = sorted(glob.glob(os.path.join(project_dir, "[0-9][0-9][0-9].wav")))
    if not wav_files:
        log("[拼接] 未找到可拼接的音频片段")
        return []

    # 建立 seq -> dialogue 信息的映射
    dialogue_map = {d["seq"]: d for d in dialogue_order}

    segments = []
    sr = 32000
    pause_samples = int(sr * pause_second)
    zero_wav = np.zeros(pause_samples, dtype=np.int16)
    timeline = []
    current_time = 0.0

    for idx, wav_path in enumerate(wav_files):
        basename = os.path.basename(wav_path)
        seq = os.path.splitext(basename)[0]  # "001"
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
        log("[拼接] 没有有效音频段可拼接")
        return []

    merged = np.concatenate(segments)
    out_path = os.path.join(project_dir, "merged.wav")
    sf.write(out_path, merged, sr)
    log(f"[拼接] 已生成合并音频: {out_path} ({len(timeline)} 个片段, 总时长 {len(merged)/sr:.1f}s)")
    return timeline


# ==================== 主入口 ====================

def main():
    parser = argparse.ArgumentParser(description="音频合成自动化链路")
    parser.add_argument("--project", required=True, help="项目编号/名称，如 P111")
    parser.add_argument("--script", required=True, help="文案文件路径")
    parser.add_argument("--output_dir", default=PROJECT_OUTPUT_DIR, help="输出根目录")
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
        top_k=args.top_k,
        top_p=args.top_p,
        temperature=args.temperature,
        speed=args.speed,
        pause_second=args.pause,
    )


if __name__ == "__main__":
    main()
