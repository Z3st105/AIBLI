"""
音频处理引擎
支持两种工作模式：
  1. 拼接模式：按时间轴顺序拼接多个零散音频文件
  2. 加载模式：直接加载用户提供的完整合成音轨
"""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from moviepy import AudioFileClip, concatenate_audioclips, CompositeAudioClip
except ImportError:
    AudioFileClip = None
    CompositeAudioClip = None
    concatenate_audioclips = None

from models.timeline import TimelineSegment

logger = logging.getLogger(__name__)


class AudioMixer:
    """
    音频混合器：负责音频的加载、拼接与时长计算
    """

    def __init__(self):
        if AudioFileClip is None:
            raise RuntimeError("moviepy 未安装，请先执行: pip install moviepy")

    # ------------------------------------------------------------------
    # 模式1：零散音频拼接（旧模式兼容）
    # ------------------------------------------------------------------

    def build_timeline(self, segments: List[TimelineSegment]) -> Tuple[Optional[object], float]:
        """
        根据时间轴片段构建完整音轨（拼接模式）。
        返回: (audio_clip_or_None, total_duration_seconds)
        """
        if not segments:
            logger.warning("没有音频片段需要拼接")
            return None, 0.0

        clips = []
        current_time = 0.0

        for seg in segments:
            if not seg.audio_path or not seg.audio_path.exists():
                logger.error(f"音频文件不存在，跳过: {seg.audio_path}")
                continue

            try:
                clip = AudioFileClip(str(seg.audio_path))
                seg.duration = clip.duration
                seg.start_time = current_time
                seg.end_time = current_time + seg.duration
                current_time = seg.end_time

                clips.append(clip)
                logger.info(f"加载音频: {seg.audio_path.name} "
                            f"时长={seg.duration:.2f}s, 起止={seg.start_time:.2f}-{seg.end_time:.2f}")
            except Exception as e:
                logger.error(f"加载音频失败 {seg.audio_path}: {e}")
                continue

        if not clips:
            return None, 0.0

        if len(clips) == 1:
            final_audio = clips[0]
        else:
            final_audio = concatenate_audioclips(clips)

        total_duration = final_audio.duration
        logger.info(f"音轨拼接完成，总时长: {total_duration:.2f}s")
        return final_audio, total_duration

    # ------------------------------------------------------------------
    # 模式2：加载完整合成音轨（新模式）
    # ------------------------------------------------------------------

    def load_full_audio(self, audio_path: Path) -> Tuple[Optional[object], float]:
        """
        直接加载用户提供的完整合成音频文件。
        返回: (audio_clip, total_duration_seconds)
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"完整音频文件不存在: {audio_path}")

        try:
            clip = AudioFileClip(str(audio_path))
            duration = clip.duration
            logger.info(f"加载完整音轨: {audio_path.name}, 总时长={duration:.2f}s")
            return clip, duration
        except Exception as e:
            logger.error(f"加载完整音轨失败 {audio_path}: {e}")
            raise

    # ------------------------------------------------------------------
    # 通用工具
    # ------------------------------------------------------------------

    @staticmethod
    def get_audio_duration(path: Path) -> float:
        """
        获取单个音频文件的时长（秒）
        """
        if AudioFileClip is None:
            return 0.0
        try:
            clip = AudioFileClip(str(path))
            dur = clip.duration
            clip.close()
            return dur
        except Exception as e:
            logger.error(f"获取音频时长失败 {path}: {e}")
            return 0.0
