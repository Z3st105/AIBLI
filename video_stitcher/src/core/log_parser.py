"""
日志/顺序文件解析器
支持两种核心模式：
  1. 顺序模式（sequence）：按列表顺序拼接零散音频
  2. 时间戳模式（timestamp）：按起止时间切换画面，配合完整音轨使用

同时支持 JSON 和纯文本两种文件格式。
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Union, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------

def parse_log_file(log_path: Path) -> Tuple[str, List[Dict[str, Any]], Union[str, None]]:
    """
    智能解析日志文件，自动检测是顺序模式还是时间戳模式。

    返回: (mode, data, audio_source)
        mode: "sequence" | "timestamp"
        data: 标准化后的列表
        audio_source: 时间戳模式下指定的完整音频文件名（可选）
    """
    if not log_path.exists():
        raise FileNotFoundError(f"日志文件不存在: {log_path}")

    suffix = log_path.suffix.lower()

    # 先尝试 JSON
    if suffix == ".json" or suffix == ".txt":
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _parse_json(data)
        except json.JSONDecodeError:
            pass

    # 降级到纯文本（仅支持顺序模式）
    seq = _parse_text_sequence(log_path)
    return "sequence", seq, None


# ---------------------------------------------------------------------------
# JSON 解析分支
# ---------------------------------------------------------------------------

def _parse_json(data: Any) -> Tuple[str, List[Dict[str, Any]], Union[str, None]]:
    """解析 JSON 结构，自动推断模式"""
    audio_source = None

    # 包装在 dict 里的情况
    if isinstance(data, dict):
        audio_source = data.get("audio_source") or data.get("audio") or data.get("source")
        mode_hint = data.get("mode", "auto")

        if "timeline" in data:
            return "timestamp", _normalize_timeline(data["timeline"]), audio_source
        if "sequence" in data:
            return "sequence", _normalize_sequence(data["sequence"]), audio_source
        if "segments" in data:
            return "timestamp", _normalize_timeline(data["segments"]), audio_source

        # 无明确字段时，尝试根据内容推断
        return _infer_dict_mode(data)

    # 直接是列表
    if isinstance(data, list):
        if not data:
            return "sequence", [], None
        first = data[0]
        if isinstance(first, dict) and ("start" in first or "end" in first or "start_time" in first):
            return "timestamp", _normalize_timeline(data), None
        return "sequence", _normalize_sequence(data), None

    raise ValueError(f"无法识别的 JSON 结构: {type(data)}")


def _infer_dict_mode(data: dict) -> Tuple[str, List[Dict[str, Any]], Union[str, None]]:
    """对只有一个顶层 key 的 dict 做最后推断"""
    audio_source = data.get("audio_source") or data.get("audio")
    for k, v in data.items():
        if isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, dict) and ("start" in first or "end" in first):
                return "timestamp", _normalize_timeline(v), audio_source
            return "sequence", _normalize_sequence(v), audio_source
    return "sequence", [], audio_source


# ---------------------------------------------------------------------------
# 顺序模式（sequence）标准化
# ---------------------------------------------------------------------------

def _normalize_sequence(seq: List[Any]) -> List[Dict[str, Any]]:
    result = []
    for item in seq:
        if isinstance(item, str):
            result.append({"character": item, "file": None})
        elif isinstance(item, dict):
            char = item.get("character") or item.get("char") or item.get("role") or item.get("name")
            file_name = item.get("file") or item.get("audio") or item.get("path")
            if char:
                result.append({"character": str(char), "file": file_name})
            else:
                logger.warning(f"跳过无法识别的顺序项: {item}")
        else:
            logger.warning(f"跳过无法识别的顺序项类型: {type(item)} -> {item}")
    return result


# ---------------------------------------------------------------------------
# 时间戳模式（timestamp）标准化
# ---------------------------------------------------------------------------

def _normalize_timeline(timeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for idx, item in enumerate(timeline):
        char = item.get("character") or item.get("char") or item.get("role") or item.get("name")
        if not char:
            logger.warning(f"时间轴第 {idx + 1} 项缺少角色名，已跳过: {item}")
            continue

        start = _parse_time(
            item.get("start") or item.get("start_time") or item.get("start_sec")
            or item.get("begin") or 0
        )
        end = _parse_time(
            item.get("end") or item.get("end_time") or item.get("end_sec")
            or item.get("stop") or 0
        )

        if end <= start:
            logger.warning(f"时间轴第 {idx + 1} 项 end<=start，已跳过: {item}")
            continue

        result.append({
            "character": str(char),
            "start": start,
            "end": end,
            "duration": end - start,
            "text": item.get("text", "")
        })
    return result


# ---------------------------------------------------------------------------
# 时间解析（支持多种人类格式）
# ---------------------------------------------------------------------------

def _parse_time(value: Any) -> float:
    """
    将多种时间格式统一转为秒（float）。
    支持:
        5.2         -> 5.2
        "5.2"       -> 5.2
        "5.2s"      -> 5.2
        "00:05"     -> 5.0
        "00:00:05"  -> 5.0
        "00:00:05.200" -> 5.2
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return 0.0

    s = value.strip()
    if not s:
        return 0.0

    # 去掉末尾单位
    s = s.rstrip("sS")

    # 纯数字
    try:
        return float(s)
    except ValueError:
        pass

    # HH:MM:SS.mmm 或 MM:SS.mmm
    parts = s.split(":")
    if len(parts) == 2:
        # MM:SS
        try:
            minutes = float(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        except ValueError:
            pass
    elif len(parts) == 3:
        # HH:MM:SS
        try:
            hours = float(parts[0])
            minutes = float(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        except ValueError:
            pass

    logger.warning(f"无法解析时间格式 '{value}'，返回 0.0")
    return 0.0


# ---------------------------------------------------------------------------
# 纯文本顺序解析（旧模式兼容）
# ---------------------------------------------------------------------------

def _parse_text_sequence(path: Path) -> List[Dict[str, str]]:
    result = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            result.append({"character": line, "file": None})
    return result


# ---------------------------------------------------------------------------
# 时间轴完整性处理（填充间隙）
# ---------------------------------------------------------------------------

def fill_gaps(timeline: List[Dict[str, Any]],
              total_duration: float,
              gap_strategy: str = "hold",
              default_character: str = "") -> List[Dict[str, Any]]:
    """
    对时间轴进行间隙填充和边界裁剪，保证连续无空白。

    gap_strategy:
        "hold"   -> 间隙延续上一个角色的画面（默认）
        "black"  -> 间隙显示黑屏（无角色）
        "stretch"-> 自动拉伸相邻片段以填满（不推荐）
    """
    if not timeline:
        return []

    # 按 start 排序
    sorted_tl = sorted(timeline, key=lambda x: x["start"])
    result = []
    current_end = 0.0
    last_character = default_character

    for seg in sorted_tl:
        # 如果当前片段开始时间晚于 current_end，说明有间隙
        if seg["start"] > current_end + 0.01:  # 0.01s 容差
            gap_duration = seg["start"] - current_end
            if gap_strategy == "hold" and last_character:
                result.append({
                    "character": last_character,
                    "start": current_end,
                    "end": seg["start"],
                    "duration": gap_duration,
                    "_gap": True
                })
            elif gap_strategy == "black":
                result.append({
                    "character": "",
                    "start": current_end,
                    "end": seg["start"],
                    "duration": gap_duration,
                    "_gap": True
                })
            # "stretch" 策略在调用方处理

        # 添加当前片段（裁剪重叠）
        start = max(seg["start"], current_end)
        end = min(seg["end"], total_duration)
        if end > start:
            entry = {
                "character": seg["character"],
                "start": start,
                "end": end,
                "duration": end - start
            }
            # 保留原始 item 中的额外字段（如 text）
            for key in ("text", "lang", "file", "seq"):
                if key in seg:
                    entry[key] = seg[key]
            result.append(entry)
            current_end = end
            last_character = seg["character"]

    # 如果最后还有空隙到 total_duration
    if current_end < total_duration - 0.01:
        if gap_strategy == "hold" and last_character:
            result.append({
                "character": last_character,
                "start": current_end,
                "end": total_duration,
                "duration": total_duration - current_end,
                "_gap": True
            })
        elif gap_strategy == "black":
            result.append({
                "character": "",
                "start": current_end,
                "end": total_duration,
                "duration": total_duration - current_end,
                "_gap": True
            })

    return result
