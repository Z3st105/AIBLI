"""
视频合成器
根据时间轴片段，将角色照片 + 音轨合成为完整视频
"""

import logging
from pathlib import Path
from typing import List, Optional

try:
    from moviepy import ImageClip, ColorClip, concatenate_videoclips, CompositeAudioClip, CompositeVideoClip
except ImportError:
    ImageClip = None
    ColorClip = None
    concatenate_videoclips = None
    CompositeAudioClip = None
    CompositeVideoClip = None

from models.timeline import TimelineSegment

logger = logging.getLogger(__name__)


class VideoBuilder:
    """
    视频构建器：
    1. 为每个时间轴片段生成静态图片的视频片段
    2. 按顺序拼接视频片段
    3. 附加完整音轨
    4. 输出最终视频文件
    """

    # 默认输出分辨率
    DEFAULT_SIZE = (1920, 1080)

    def __init__(self, output_size: tuple = DEFAULT_SIZE, fps: int = 24):
        if ImageClip is None:
            raise RuntimeError("moviepy 未安装，请先执行: pip install moviepy")
        self.output_size = output_size
        self.fps = fps

    def build(self, segments: List[TimelineSegment],
              audio_clip: Optional[object],
              output_path: Path,
              subtitle_clips: Optional[List] = None) -> Path:
        """
        构建完整视频并输出到指定路径
        subtitle_clips: 可选的字幕 ImageClip 列表，将叠加在视频上方
        """
        if not segments:
            raise ValueError("没有视频片段可以构建")

        video_clips = []

        for seg in segments:
            photo = seg.photo_path
            if not photo or not photo.exists():
                logger.warning(f"角色 '{seg.character_name}' 没有照片，使用黑色占位")
                # 没有照片时生成黑色片段（moviepy 支持纯色片段）
                clip = self._create_black_clip(seg.duration)
            else:
                clip = self._create_image_clip(photo, seg.duration)

            video_clips.append(clip)
            logger.info(f"视频片段: {seg.character_name}, 时长={seg.duration:.2f}s")

        # 拼接视频
        if len(video_clips) == 1:
            final_video = video_clips[0]
        else:
            final_video = concatenate_videoclips(video_clips, method="compose")

        # 叠加字幕层（如有）
        if subtitle_clips:
            final_video = CompositeVideoClip(
                [final_video] + subtitle_clips,
                size=self.output_size
            )
            logger.info(f"已叠加 {len(subtitle_clips)} 个字幕片段")

        # 附加音轨
        if audio_clip is not None:
            final_video = final_video.with_audio(audio_clip)
            logger.info("已附加音轨")

        # 输出
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"开始渲染视频到: {output_path}")
        final_video.write_videofile(
            str(output_path),
            fps=self.fps,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=str(output_path.with_suffix(".m4a")),
            remove_temp=True,
            threads=4,
            preset="medium",
            logger=None  # 可由调用方控制
        )

        # 清理资源
        final_video.close()
        for vc in video_clips:
            vc.close()

        logger.info(f"视频渲染完成: {output_path}")
        return output_path

    def _create_image_clip(self, image_path: Path, duration: float):
        """
        从图片创建指定时长的视频片段。
        采用 cover 模式：等比缩放，占满画面，居中裁剪，不拉伸。
        """
        clip = ImageClip(str(image_path), duration=duration)
        img_w, img_h = clip.size
        target_w, target_h = self.output_size

        # 计算 cover 缩放比例：让图片完全覆盖目标区域
        scale = max(target_w / img_w, target_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)

        # 等比缩放到覆盖尺寸
        clip = clip.resized(new_size=(new_w, new_h))

        # 居中裁剪到目标分辨率
        x1 = (new_w - target_w) // 2
        y1 = (new_h - target_h) // 2
        x2 = x1 + target_w
        y2 = y1 + target_h
        clip = clip.cropped(x1=x1, y1=y1, x2=x2, y2=y2)

        return clip.with_fps(self.fps)

    def _create_black_clip(self, duration: float):
        """
        创建纯色（黑色）视频片段作为占位
        """
        clip = ColorClip(size=self.output_size, color=(0, 0, 0), duration=duration)
        return clip.with_fps(self.fps)
