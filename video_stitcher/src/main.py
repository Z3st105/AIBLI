"""
视频拼接主入口（双模式）

模式A - 顺序模式（sequence）：
    用户提供零散音频 + 顺序日志，程序自动拼接音轨并按序切镜
    日志: sequence.json / sequence.txt

模式B - 时间戳模式（timestamp）：
    用户提供完整合成音频 + 时间戳日志，程序直接加载音轨并按时间切镜
    日志: timeline.json / log.json（含 start/end 字段）

用法示例:
    python src/main.py --project 111
    python src/main.py --project 111 --output D:\\output\\final.mp4
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

# 将 src 加入路径（支持直接从项目根目录运行）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from core.project_scanner import ProjectScanner
from core.log_parser import parse_log_file, fill_gaps
from core.audio_mixer import AudioMixer
from core.video_builder import VideoBuilder
from core.subtitle_renderer import build_subtitle_clips, load_subtitle_config, load_character_subtitle_config
from models.character import Character
from models.timeline import TimelineSegment

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("VideoStitcher")


# ---------------------------------------------------------------------------
# 模式A：顺序模式（零散音频拼接）
# ---------------------------------------------------------------------------

def build_timeline_from_sequence(
    sequence: List[Dict[str, Optional[str]]],
    characters: Dict[str, Character],
    project_id: str
) -> List[TimelineSegment]:
    """
    根据顺序描述和角色对象，构建完整的时间轴（旧模式）。
    """
    segments: List[TimelineSegment] = []
    char_indices: Dict[str, int] = {name: 0 for name in characters}

    for idx, item in enumerate(sequence):
        char_name = item["character"]
        specified_file = item.get("file")

        if char_name not in characters:
            logger.error(f"第 {idx + 1} 个顺序项引用了未知角色 '{char_name}'，已跳过")
            continue

        char = characters[char_name]
        audios = char.project_audios.get(project_id, [])

        if not audios:
            logger.error(f"角色 '{char_name}' 在项目 '{project_id}' 下没有音频，已跳过")
            continue

        audio_path: Optional[Path] = None
        if specified_file:
            for a in audios:
                if a.name == specified_file or a.stem == specified_file:
                    audio_path = a
                    break
            if audio_path is None:
                logger.warning(
                    f"角色 '{char_name}' 未找到指定音频 '{specified_file}'，fallback 到顺序索引"
                )

        if audio_path is None:
            ptr = char_indices[char_name]
            if ptr >= len(audios):
                logger.error(
                    f"角色 '{char_name}' 的音频已耗尽（需要第 {ptr + 1} 个，"
                    f"但只有 {len(audios)} 个），已跳过"
                )
                continue
            audio_path = audios[ptr]
            char_indices[char_name] = ptr + 1

        seg = TimelineSegment(
            character_name=char_name,
            audio_path=audio_path,
            photo_path=char.photo_path
        )
        segments.append(seg)
        logger.info(f"时间轴[{idx + 1}]: {char_name} -> {audio_path.name}")

    return segments


def run_sequence_mode(
    scanner: ProjectScanner,
    project_id: str,
    project_chars: Dict[str, Character],
    log_file: Path,
    output_path: Path,
    resolution: tuple,
    fps: int,
    subtitle_config: Optional[Path] = None
) -> Path:
    """执行顺序模式：拼接零散音频 + 按序切镜"""
    mode, sequence, _ = parse_log_file(log_file)
    if mode != "sequence":
        logger.warning(f"日志被解析为 {mode} 模式，但当前按顺序模式处理")

    logger.info(f"【顺序模式】解析到 {len(sequence)} 个顺序项")
    segments = build_timeline_from_sequence(sequence, project_chars, project_id)
    if not segments:
        raise RuntimeError("没有有效的时间轴片段，无法生成视频")

    mixer = AudioMixer()
    audio_clip, total_duration = mixer.build_timeline(segments)
    logger.info(f"总音频时长: {total_duration:.2f}s")

    sub_cfg = load_subtitle_config(subtitle_config)
    char_styles = _build_character_styles(project_chars)
    subtitle_clips = build_subtitle_clips(segments, resolution[0], resolution[1], sub_cfg, char_styles)

    builder = VideoBuilder(output_size=resolution, fps=fps)
    final_path = builder.build(segments, audio_clip, output_path, subtitle_clips)

    _save_meta(output_path, project_id, resolution, fps, total_duration, segments, mode="sequence")
    return final_path


# ---------------------------------------------------------------------------
# 模式B：时间戳模式（完整音轨 + 时间戳切镜）
# ---------------------------------------------------------------------------

def build_timeline_from_timestamp(
    timeline: List[Dict[str, Any]],
    characters: Dict[str, Character],
    total_duration: float
) -> List[TimelineSegment]:
    """
    根据时间戳日志构建时间轴，并自动填充间隙。
    """
    # 填充间隙，保证连续性
    filled = fill_gaps(timeline, total_duration, gap_strategy="hold")

    segments: List[TimelineSegment] = []
    for idx, item in enumerate(filled):
        char_name = item["character"]
        is_gap = item.get("_gap", False)

        if char_name and char_name not in characters:
            logger.error(f"时间轴第 {idx + 1} 项引用了未知角色 '{char_name}'，已跳过")
            continue

        photo = characters[char_name].photo_path if char_name in characters else None

        seg = TimelineSegment(
            character_name=char_name or "(gap)",
            audio_path=None,
            photo_path=photo,
            start_time=item["start"],
            end_time=item["end"],
            duration=item["duration"],
            is_gap=is_gap,
            text=item.get("text", "")
        )
        segments.append(seg)
        gap_mark = " [间隙填充]" if is_gap else ""
        logger.info(f"时间轴[{idx + 1}]: {seg.character_name} "
                    f"{seg.start_time:.2f}s - {seg.end_time:.2f}s ({seg.duration:.2f}s){gap_mark}")

    return segments


def run_timestamp_mode(
    scanner: ProjectScanner,
    project_id: str,
    project_chars: Dict[str, Character],
    log_file: Path,
    output_path: Path,
    resolution: tuple,
    fps: int,
    source_dir: Optional[Path] = None,
    subtitle_config: Optional[Path] = None
) -> Path:
    """执行时间戳模式：加载完整音轨 + 按时间戳切镜"""
    mode, timeline, audio_source_hint = parse_log_file(log_file)
    if mode != "timestamp":
        logger.warning(f"日志被解析为 {mode} 模式，但当前按时间戳模式处理")

    logger.info(f"【时间戳模式】解析到 {len(timeline)} 个时间戳片段")

    # 查找完整音频
    if source_dir:
        # 桥梁模式：直接从 source_dir 读取音频
        full_audio_path = _find_audio_in_source_dir(source_dir, hint_name=audio_source_hint)
    else:
        full_audio_path = scanner.find_full_audio(project_id, hint_name=audio_source_hint)

    if full_audio_path is None:
        raise FileNotFoundError(
            f"未找到项目 '{project_id}' 的完整合成音频。\n"
            f"请将合成好的音频文件（如 full_audio.wav / merged.wav）"
            f"{'放在 --source-dir 指定的目录下' if source_dir else '放在任一角色目录的 projects/' + project_id + '/ 下'}。"
        )
    logger.info(f"找到完整音轨: {full_audio_path}")

    # 加载完整音轨
    mixer = AudioMixer()
    audio_clip, total_duration = mixer.load_full_audio(full_audio_path)
    logger.info(f"音轨总时长: {total_duration:.2f}s")

    # 构建时间轴
    segments = build_timeline_from_timestamp(timeline, project_chars, total_duration)
    if not segments:
        raise RuntimeError("没有有效的时间轴片段，无法生成视频")

    # 验证时间轴覆盖范围
    video_duration = sum(s.duration for s in segments)
    logger.info(f"画面总时长: {video_duration:.2f}s")
    if abs(video_duration - total_duration) > 0.1:
        logger.warning(f"画面总时长({video_duration:.2f}s)与音频时长({total_duration:.2f}s)不一致")

    # 生成字幕
    sub_cfg = load_subtitle_config(subtitle_config)
    char_styles = _build_character_styles(project_chars)
    subtitle_clips = build_subtitle_clips(segments, resolution[0], resolution[1], sub_cfg, char_styles)

    # 合成视频
    builder = VideoBuilder(output_size=resolution, fps=fps)
    final_path = builder.build(segments, audio_clip, output_path, subtitle_clips)

    _save_meta(output_path, project_id, resolution, fps, total_duration, segments,
               mode="timestamp", audio_source=str(full_audio_path))
    return final_path


def _find_audio_in_source_dir(source_dir: Path, hint_name: Optional[str] = None) -> Optional[Path]:
    """在音频合成部门的输出目录中查找完整音频文件"""
    audio_exts = [".wav", ".mp3", ".aac", ".flac", ".m4a", ".ogg"]
    common_names = ["full_audio", "combined", "audio", "merged", "final_audio", "output"]

    # 按 hint 精确匹配
    if hint_name:
        hint_path = source_dir / hint_name
        if hint_path.exists():
            return hint_path

    # 按常见名称搜索
    for name in common_names:
        for ext in audio_exts:
            cand = source_dir / f"{name}{ext}"
            if cand.exists():
                return cand

    # 兜底：找目录下最大的音频文件
    all_audios = []
    for ext in audio_exts:
        all_audios.extend(source_dir.glob(f"*{ext}"))
    if all_audios:
        all_audios.sort(key=lambda p: p.stat().st_size, reverse=True)
        return all_audios[0]

    return None


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------

def _build_character_styles(project_chars: Dict[str, Character]) -> Dict[str, Dict[str, Any]]:
    """为每个参与角色加载独立的字幕样式配置。"""
    styles = {}
    for name, char in project_chars.items():
        char_cfg = load_character_subtitle_config(char.root_path)
        if char_cfg:
            styles[name] = char_cfg
    return styles


def _save_meta(output_path: Path, project_id: str, resolution: tuple, fps: int,
               total_duration: float, segments: List[TimelineSegment],
               mode: str = "unknown", audio_source: Optional[str] = None):
    """保存元数据 JSON"""
    meta_path = output_path.with_suffix(".json")
    meta = {
        "project_id": project_id,
        "mode": mode,
        "output": str(output_path),
        "audio_source": audio_source,
        "resolution": resolution,
        "fps": fps,
        "total_duration": total_duration,
        "segments": [
            {
                "index": i + 1,
                "character": s.character_name,
                "audio": s.audio_path.name if s.audio_path else None,
                "photo": str(s.photo_path) if s.photo_path else None,
                "start": s.start_time,
                "end": s.end_time,
                "duration": s.duration,
                "is_gap": s.is_gap
            }
            for i, s in enumerate(segments)
        ]
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    logger.info(f"元数据已保存: {meta_path}")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _infer_resolution_from_photos(characters: Dict[str, Character]) -> tuple:
    """
    根据角色照片的比例自动推断最合适的输出分辨率。
    竖向照片居多 -> 1080x1920（短视频竖屏）
    横向照片居多 -> 1920x1080（横屏）
    正方形或无法判断 -> 1080x1920（默认竖屏）
    """
    if not characters:
        return (1080, 1920)

    portrait_count = 0
    landscape_count = 0

    for char in characters.values():
        w, h = char.get_photo_dimensions()
        if w > 0 and h > 0:
            if h > w * 1.1:
                portrait_count += 1
            elif w > h * 1.1:
                landscape_count += 1
            # 正方形不偏向任何一方

    if landscape_count > portrait_count:
        return (1920, 1080)
    return (1080, 1920)


def run_project(project_id: str,
                characters_dir: Optional[Path] = None,
                output_path: Optional[Path] = None,
                resolution: Optional[tuple] = None,
                fps: int = 24,
                source_dir: Optional[Path] = None,
                subtitle_config: Optional[Path] = None):
    """
    执行单个项目的视频拼接（自动检测模式）

    source_dir: 音频合成部门的输出目录（桥梁模式）。
                指定后，直接从该目录读取 timeline.json 和完整音频，
                无需手动复制到 characters/ 目录。
    resolution: 输出分辨率 (width, height)。None 则根据照片自动推断。
    """
    if characters_dir is None:
        characters_dir = _PROJECT_ROOT / "characters"
    characters_dir = Path(characters_dir)

    if output_path is None:
        output_path = _PROJECT_ROOT / "output" / f"{project_id}.mp4"
    output_path = Path(output_path)

    source_dir = Path(source_dir) if source_dir else None

    # 1. 扫描角色和项目
    logger.info(f"=== 开始处理项目: {project_id} ===")
    scanner = ProjectScanner(characters_dir)
    scanner.scan_all()

    # 桥梁模式：不需要项目目录存在于 characters/ 中
    # 直接从 source_dir 读取日志，然后匹配 characters/ 下的角色照片
    if source_dir:
        logger.info(f"【桥梁模式】音频包来源: {source_dir}")
        # 先解析日志获取所需角色，再推断分辨率
        log_candidates = ["timeline.json", "log.json", "sequence.json"]
        log_file = None
        for cand in log_candidates:
            p = source_dir / cand
            if p.exists():
                log_file = p
                break
        if log_file:
            mode, timeline, _ = parse_log_file(log_file)
            required_chars = set()
            for item in timeline:
                char = item.get("character") or item.get("char") or item.get("role") or item.get("name")
                if char:
                    required_chars.add(char)
            project_chars = {name: scanner.characters[name] for name in required_chars if name in scanner.characters}
            if resolution is None:
                resolution = _infer_resolution_from_photos(project_chars)
                logger.info(f"自动推断分辨率: {resolution[0]}x{resolution[1]}")
        if resolution is None:
            resolution = (1080, 1920)
        return _run_bridge_mode(
            scanner, project_id, source_dir, output_path, resolution, fps, subtitle_config
        )

    # 传统模式：项目数据在 characters/ 目录内
    if project_id not in scanner.projects:
        raise FileNotFoundError(
            f"未找到项目 '{project_id}'。已发现项目: {list(scanner.projects.keys()) or '无'}"
        )

    project_chars = scanner.get_characters_for_project(project_id)
    logger.info(f"项目 '{project_id}' 参与角色: {list(project_chars.keys())}")

    if resolution is None:
        resolution = _infer_resolution_from_photos(project_chars)
        logger.info(f"自动推断分辨率: {resolution[0]}x{resolution[1]}")

    # 2. 查找日志
    log_file = scanner.find_log_file(project_id)

    # 3. 无日志时的 fallback
    if log_file is None:
        if len(project_chars) == 1:
            # 单角色且无日志：检查是否有完整音频（时间戳模式的最简形态）
            full_audio = scanner.find_full_audio(project_id)
            if full_audio:
                logger.info(f"未找到日志，但发现完整音轨: {full_audio}")
                logger.info("尝试以时间戳模式运行（单角色全段）")
                dur = AudioMixer.get_audio_duration(full_audio)
                timeline = [{"character": list(project_chars.keys())[0], "start": 0.0, "end": dur}]
                filled = fill_gaps(timeline, dur, gap_strategy="hold")
                segments = build_timeline_from_timestamp(filled, project_chars, dur)
                mixer = AudioMixer()
                audio_clip, total_duration = mixer.load_full_audio(full_audio)
                sub_cfg = load_subtitle_config(subtitle_config)
                char_styles = _build_character_styles(project_chars)
                subtitle_clips = build_subtitle_clips(segments, resolution[0], resolution[1], sub_cfg, char_styles)
                builder = VideoBuilder(output_size=resolution, fps=fps)
                final_path = builder.build(segments, audio_clip, output_path, subtitle_clips)
                _save_meta(output_path, project_id, resolution, fps, total_duration,
                           segments, mode="timestamp", audio_source=str(full_audio))
                return final_path
            # 否则走旧单角色顺序模式
            sole_char = list(project_chars.keys())[0]
            audios = project_chars[sole_char].project_audios.get(project_id, [])
            sequence = [{"character": sole_char, "file": a.name} for a in audios]
            logger.info(f"单角色顺序模式：按文件名顺序取 {len(sequence)} 个音频")
            segments = build_timeline_from_sequence(sequence, project_chars, project_id)
            mixer = AudioMixer()
            audio_clip, total_duration = mixer.build_timeline(segments)
            sub_cfg = load_subtitle_config(subtitle_config)
            char_styles = _build_character_styles(project_chars)
            subtitle_clips = build_subtitle_clips(segments, resolution[0], resolution[1], sub_cfg, char_styles)
            builder = VideoBuilder(output_size=resolution, fps=fps)
            final_path = builder.build(segments, audio_clip, output_path, subtitle_clips)
            _save_meta(output_path, project_id, resolution, fps, total_duration, segments, mode="sequence")
            return final_path
        else:
            raise FileNotFoundError(
                f"项目 '{project_id}' 有多个角色但未找到日志/顺序文件。\n"
                f"请在任一角色目录 projects/{project_id}/ 下放置日志文件。"
            )

    # 4. 有日志：解析并自动选择模式
    logger.info(f"找到日志文件: {log_file}")
    mode, parsed_data, audio_source_hint = parse_log_file(log_file)
    logger.info(f"日志模式识别为: {mode}")

    if mode == "timestamp":
        return run_timestamp_mode(
            scanner, project_id, project_chars, log_file,
            output_path, resolution, fps, subtitle_config=subtitle_config
        )
    else:
        return run_sequence_mode(
            scanner, project_id, project_chars, log_file,
            output_path, resolution, fps, subtitle_config=subtitle_config
        )


def _run_bridge_mode(
    scanner: ProjectScanner,
    project_id: str,
    source_dir: Path,
    output_path: Path,
    resolution: tuple,
    fps: int,
    subtitle_config: Optional[Path] = None
) -> Path:
    """
    桥梁模式：直接对接音频合成部门的输出包。
    从 source_dir 读取 timeline.json + 完整音频，
    从 characters/ 读取角色照片。
    """
    if not source_dir.exists():
        raise FileNotFoundError(f"音频包目录不存在: {source_dir}")

    # 读取日志
    log_candidates = ["timeline.json", "log.json", "sequence.json"]
    log_file: Optional[Path] = None
    for cand in log_candidates:
        p = source_dir / cand
        if p.exists():
            log_file = p
            break

    if log_file is None:
        raise FileNotFoundError(
            f"音频包中未找到日志文件。期望找到: {', '.join(log_candidates)}"
        )

    # 解析日志
    mode, timeline, audio_source_hint = parse_log_file(log_file)
    logger.info(f"日志模式识别为: {mode}")

    if mode != "timestamp":
        logger.warning(f"桥梁模式推荐使用时间戳日志，当前识别为 {mode}")

    # 从 timeline 中提取所有角色名
    required_chars = set()
    for item in timeline:
        char = item.get("character") or item.get("char") or item.get("role") or item.get("name")
        if char:
            required_chars.add(char)

    logger.info(f"日志涉及角色: {sorted(required_chars)}")

    # 在 characters/ 中匹配角色
    all_chars = scanner.characters
    project_chars: Dict[str, Character] = {}
    missing_chars = []

    for char_name in required_chars:
        if char_name in all_chars:
            project_chars[char_name] = all_chars[char_name]
        else:
            missing_chars.append(char_name)

    if missing_chars:
        raise FileNotFoundError(
            f"以下角色在 characters/ 目录中未找到对应文件夹: {missing_chars}\n"
            f"请确保 characters/ 下存在以下文件夹（含照片）: {sorted(required_chars)}"
        )

    logger.info(f"成功匹配角色: {list(project_chars.keys())}")

    # 运行时间戳模式（指定 source_dir 以读取音频）
    return run_timestamp_mode(
        scanner, project_id, project_chars, log_file,
        output_path, resolution, fps, source_dir=source_dir,
        subtitle_config=subtitle_config
    )


def main():
    parser = argparse.ArgumentParser(description="多角色音画同步视频拼接工具（顺序/时间戳双模式）")
    parser.add_argument("--project", "-p", required=True, help="项目ID（如 111）")
    parser.add_argument("--characters-dir", "-c", default=None,
                        help="角色根目录路径（默认: ./characters）")
    parser.add_argument("--source-dir", "-s", default=None,
                        help="音频合成部门输出包路径（桥梁模式）。指定后直接从该目录读取 merged.wav + timeline.json")
    parser.add_argument("--output", "-o", default=None, help="输出视频路径")
    parser.add_argument("--width", type=int, default=None, help="视频宽度（默认自动推断）")
    parser.add_argument("--height", type=int, default=None, help="视频高度（默认自动推断）")
    parser.add_argument("--fps", type=int, default=24, help="帧率（默认24）")
    parser.add_argument("--subtitle-config", default=None,
                        help="字幕样式配置文件路径（默认: ./subtitle_config.json）")
    args = parser.parse_args()

    resolution = None
    if args.width is not None and args.height is not None:
        resolution = (args.width, args.height)

    final = run_project(
        project_id=args.project,
        characters_dir=Path(args.characters_dir) if args.characters_dir else None,
        output_path=Path(args.output) if args.output else None,
        resolution=resolution,
        fps=args.fps,
        source_dir=Path(args.source_dir) if args.source_dir else None,
        subtitle_config=Path(args.subtitle_config) if args.subtitle_config else None
    )
    print(f"\n视频已生成: {final}")


if __name__ == "__main__":
    main()
