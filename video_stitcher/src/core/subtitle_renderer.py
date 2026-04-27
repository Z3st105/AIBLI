"""
字幕渲染器
基于 Pillow 生成文字图片，不依赖 ImageMagick，支持中文。

样式通过 subtitle_config.json 控制，可调整：
  - font_size, color, stroke_color, stroke_width
  - font_path（可指定字体文件，留空则自动探测系统字体）
  - position（bottom 等）
  - margin_bottom, max_width_ratio, line_spacing
"""

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

try:
    from moviepy import ImageClip, CompositeVideoClip
except ImportError:
    ImageClip = None
    CompositeVideoClip = None

from models.timeline import TimelineSegment

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CONFIG = {
    "enabled": True,
    "font_size": 44,
    "color": "#FFFFFF",
    "stroke_color": "#000000",
    "stroke_width": 2,
    "font_path": None,          # 可指定绝对路径；None 时自动探测
    "position": "bottom",
    "margin_bottom": 90,
    "max_width_ratio": 0.85,
    "line_spacing": 1.3,
    "bg_color": None,           # 字幕背景色，None=透明
    "bg_padding": 10,
    "bg_radius": 8,
    # 字幕切割配置（新增）
    "max_lines_per_subtitle": 2,   # 每条字幕最大行数，超过则自动切分
    "min_subtitle_duration": 1.5,   # 每条字幕最短显示时间（秒），避免闪现
    "split_long_text": True,       # 是否启用长文本自动切分
}

# Windows 常见中文字体候选
_WIN_FONT_CANDIDATES = [
    "msyh.ttc",        # 微软雅黑
    "msyhbd.ttc",      # 微软雅黑 Bold
    "simhei.ttf",      # 黑体
    "simsun.ttc",      # 宋体
    "simkai.ttf",      # 楷体
    "msgothic.ttc",    # MS Gothic（日文兼容）
    "meiryo.ttc",      # Meiryo（日文）
]


def _find_system_font() -> Optional[str]:
    """自动探测系统可用字体（优先中文字体）。"""
    if os.name == "nt":
        font_dir = Path(r"C:\Windows\Fonts")
        for name in _WIN_FONT_CANDIDATES:
            p = font_dir / name
            if p.exists():
                return str(p)
    else:
        # Linux/macOS 常见路径
        candidates = [
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
        ]
        for c in candidates:
            if Path(c).exists():
                return c
    return None


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """将 #RRGGBB 转为 (R, G, B)"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join([c * 2 for c in hex_color])
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """按最大像素宽度对文本进行自动换行。"""
    if not text:
        return []

    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = []
    current_line = ""

    for char in text:
        test_line = current_line + char
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_width = bbox[2] - bbox[0]
        if line_width > max_width and current_line:
            lines.append(current_line)
            current_line = char
        else:
            current_line = test_line

    if current_line:
        lines.append(current_line)

    return lines if lines else [text]


# 中文句子分隔标点
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[。！？；…\n])\s*')

# 强制最大字符数（超过这个数强制断句，防止单句过长）
_MAX_CHARS_PER_SUBTITLE = 40


def _split_text_by_sentences(text: str, max_chars: int = _MAX_CHARS_PER_SUBTITLE) -> List[str]:
    """
    将长文本按句子切分为多个短片段。
    
    规则：
    1. 按中文句号、感叹号、问号、分号、省略号、换行符切分
    2. 如果单段仍超长（>max_chars），按逗号/空格二次拆分
    3. 最终每段控制在 max_chars 以内
    
    返回：切分后的文本列表，每个元素适合作为一条字幕显示
    """
    import re
    text = text.strip()
    if not text:
        return []

    # 第一步：按句末标点切分
    parts = _SENTENCE_SPLIT_RE.split(text)
    parts = [p.strip() for p in parts if p.strip()]

    # 第二步：对超长部分做二次拆分（按逗号/顿号）
    result = []
    for part in parts:
        while len(part) > max_chars:
            # 找到 max_chars 内最近的逗号/顿号/空格位置
            cut_pos = -1
            for sep in ('，', '、', ',', ' ', '：', ':'):
                pos = part.rfind(sep, 0, max_chars + 1)
                if pos > cut_pos:
                    cut_pos = pos

            if cut_pos <= 0:
                # 找不到合适的分隔符，硬切
                cut_pos = max_chars

            result.append(part[:cut_pos + 1].strip())
            part = part[cut_pos + 1:].strip()

        if part:
            result.append(part)

    return result if result else [text]


def _estimate_subtitle_lines(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> int:
    """估算一段文字渲染后会占多少行（用于判断是否需要进一步拆分）。"""
    lines = _wrap_text(text, font, max_width)
    return len(lines)


def _render_text_image(
    text: str,
    video_width: int,
    video_height: int,
    config: Dict[str, Any]
) -> Optional[Image.Image]:
    """
    用 Pillow 将单条字幕文本渲染为透明背景图片。
    返回 PIL Image（RGBA），可直接传给 moviepy ImageClip。
    """
    if Image is None or not text.strip():
        return None

    font_size = config.get("font_size", 48)
    color_hex = config.get("color", "#FFFFFF")
    stroke_hex = config.get("stroke_color", "#000000")
    stroke_width = config.get("stroke_width", 2)
    font_path = config.get("font_path")
    max_width_ratio = config.get("max_width_ratio", 0.85)
    line_spacing = config.get("line_spacing", 1.2)
    bg_color = config.get("bg_color")
    bg_padding = config.get("bg_padding", 10)
    bg_radius = config.get("bg_radius", 8)

    # 解析颜色
    text_color = _hex_to_rgb(color_hex)
    stroke_color = _hex_to_rgb(stroke_hex)
    bg_rgba = _hex_to_rgb(bg_color) + (200,) if bg_color else None

    # 加载字体
    if font_path and Path(font_path).exists():
        font_file = font_path
    else:
        font_file = _find_system_font()

    if font_file is None:
        logger.warning("未找到可用字体，字幕将使用默认字体（可能不支持中文）")
        font = ImageFont.load_default()
    else:
        try:
            font = ImageFont.truetype(font_file, font_size)
        except Exception as e:
            logger.warning(f"加载字体失败 {font_file}: {e}，回退到默认字体")
            font = ImageFont.load_default()

    # 自动换行
    max_text_width = int(video_width * max_width_ratio)
    lines = _wrap_text(text.strip(), font, max_text_width)
    if not lines:
        return None

    # 计算整体尺寸
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    max_line_width = max(line_widths)
    total_text_height = sum(line_heights)
    if len(lines) > 1:
        total_text_height += int((len(lines) - 1) * line_heights[0] * (line_spacing - 1))

    # 如果有背景，加上 padding
    img_width = max_line_width + bg_padding * 2
    img_height = total_text_height + bg_padding * 2

    # 居中
    img = Image.new("RGBA", (img_width, img_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 画背景
    if bg_rgba:
        draw.rounded_rectangle(
            [(0, 0), (img_width, img_height)],
            radius=bg_radius,
            fill=bg_rgba
        )

    # 画文字（带描边）
    y = bg_padding
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        line_h = bbox[3] - bbox[1]
        x = (img_width - line_w) // 2

        # 描边：向四周偏移画文字
        if stroke_width > 0:
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx == 0 and dy == 0:
                        continue
                    draw.text((x + dx, y + dy), line, font=font, fill=stroke_color)

        # 主文字
        draw.text((x, y), line, font=font, fill=text_color)
        y += int(line_h * line_spacing)

    return img


def build_subtitle_clips(
    segments: List[TimelineSegment],
    video_width: int,
    video_height: int,
    config: Optional[Dict[str, Any]] = None,
    character_styles: Optional[Dict[str, Dict[str, Any]]] = None
) -> List[Any]:
    """
    为时间轴片段生成字幕 ImageClip 列表。
    返回的列表可直接传给 CompositeVideoClip。

    新增功能：长文本自动按句子切分为多条字幕，时间均分匹配语音节奏。

    character_styles: {角色名: 该角色的字幕样式覆盖}，优先级高于全局配置。
    """
    if ImageClip is None:
        logger.warning("moviepy 未安装，无法生成字幕")
        return []

    base_cfg = {**DEFAULT_CONFIG, **(config or {})}
    if not base_cfg.get("enabled", True):
        return []

    split_enabled = base_cfg.get("split_long_text", True)
    max_lines_per_sub = base_cfg.get("max_lines_per_subtitle", 2)
    min_duration = base_cfg.get("min_subtitle_duration", 1.5)

    character_styles = character_styles or {}
    clips = []

    for seg in segments:
        if not seg.text or seg.text.strip() == "" or seg.is_gap:
            continue

        # 合并配置：全局 -> 角色专属
        char_cfg = character_styles.get(seg.character_name, {})
        cfg = {**base_cfg, **char_cfg}
        margin_bottom = cfg.get("margin_bottom", 90)

        # ====== 判断是否需要切割 ======
        text = seg.text.strip()
        need_split = False

        if split_enabled and text:
            # 用一个临时字体估算行数（粗筛）
            font_for_check = _get_font_for_size(cfg.get("font_size", 44), cfg.get("font_path"))
            max_text_width = int(video_width * cfg.get("max_width_ratio", 0.85))
            est_lines = _estimate_subtitle_lines(text, font_for_check, max_text_width)

            if est_lines > max_lines_per_sub:
                need_split = True

        if not need_split:
            # 短文本：直接渲染一条字幕（原有逻辑）
            img = _render_text_image(text, video_width, video_height, cfg)
            if img is not None:
                clip = _create_subtitle_clip(img, seg.start_time, seg.duration,
                                             video_height, margin_bottom)
                if clip:
                    clips.append(clip)
                    logger.info(f"字幕片段(单条): [{seg.character_name}] '{text[:30]}...' "
                                f"{seg.start_time:.2f}s - {seg.end_time:.2f}s")
        else:
            # 长文本：按句子切割，时间均分
            sub_parts = _split_text_by_sentences(text)
            
            # 计算每部分的时间占比（按字符长度比例分配，更贴合语速）
            total_chars = sum(len(p) for p in sub_parts)
            if total_chars == 0:
                continue

            elapsed_time = 0.0
            for i, part_text in enumerate(sub_parts):
                # 时间分配：按字符数比例 + 最小时长保护
                char_ratio = len(part_text) / total_chars
                part_duration = max(seg.duration * char_ratio, min_duration)

                # 最后一段用剩余时间（避免浮点误差导致溢出）
                if i == len(sub_parts) - 1:
                    part_duration = seg.duration - elapsed_time
                    if part_duration < 0.1:
                        part_duration = min_duration

                part_start = seg.start_time + elapsed_time

                img = _render_text_image(part_text, video_width, video_height, cfg)
                if img is None:
                    elapsed_time += part_duration
                    continue

                clip = _create_subtitle_clip(img, part_start, part_duration,
                                             video_height, margin_bottom)
                if clip:
                    clips.append(clip)
                    logger.info(
                        f"字幕片段(切分{i+1}/{len(sub_parts)}): "
                        f"[{seg.character_name}] '{part_text[:25]}...' "
                        f"{part_start:.2f}s - {part_start + part_duration:.2f}s "
                        f"({part_duration:.1f}s)"
                    )

                elapsed_time += part_duration

                # 防止超出 segment 范围
                if elapsed_time >= seg.duration - 0.05:
                    break

    logger.info(f"共生成 {len(clips)} 个字幕片段")
    return clips


def _get_font_for_size(font_size: int, font_path: Optional[str]) -> ImageFont.FreeTypeFont:
    """快速获取指定大小的字体对象（用于行数估算）。"""
    try:
        if font_path and Path(font_path).exists():
            return ImageFont.truetype(str(font_path), font_size)
        sys_font = _find_system_font()
        if sys_font:
            return ImageFont.truetype(sys_font, font_size)
    except Exception:
        pass
    return ImageFont.load_default()


def _create_subtitle_clip(img: Image.Image, start_time: float, duration: float,
                          video_height: int, margin_bottom: int) -> Optional[Any]:
    """从 PIL Image 创建定位好的字幕 ImageClip。"""
    # 保存临时文件（moviepy ImageClip 需要文件路径）
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(tmp_fd)
    img.save(tmp_path, "PNG")

    # 生成 ImageClip
    sub_clip = ImageClip(tmp_path, duration=duration)

    # 定位：底部居中
    def _position(t, clip=sub_clip, vh=video_height, mb=margin_bottom):
        _, ch = clip.size
        return ("center", vh - mb - ch)

    sub_clip = sub_clip.with_position(_position).with_start(start_time)
    return sub_clip


def load_character_subtitle_config(character_root: Path) -> Dict[str, Any]:
    """
    加载角色独立的字幕样式配置。
    期望路径: <character_root>/profile/subtitle_style.json
    """
    import json
    style_path = character_root / "profile" / "subtitle_style.json"
    if not style_path.exists():
        return {}
    try:
        with open(style_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        logger.info(f"已加载角色字幕样式: {style_path}")
        return cfg
    except Exception as e:
        logger.warning(f"加载角色字幕样式失败 {style_path}: {e}")
        return {}


def load_subtitle_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载字幕配置文件，找不到则返回默认配置。"""
    import json
    if path is None:
        # 默认查找项目根目录下的 subtitle_config.json
        root = Path(__file__).resolve().parent.parent
        path = root / "subtitle_config.json"

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            logger.info(f"已加载字幕配置: {path}")
            return {**DEFAULT_CONFIG, **user_cfg}
        except Exception as e:
            logger.warning(f"加载字幕配置失败: {e}，使用默认配置")

    return DEFAULT_CONFIG.copy()
