"""
项目扫描器：发现所有角色，并找出共同的项目
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

from models.character import Character

logger = logging.getLogger(__name__)


class ProjectScanner:
    """
    扫描 characters/ 目录，构建角色索引和项目索引
    """

    def __init__(self, characters_dir: Path):
        self.characters_dir = Path(characters_dir)
        self.characters: Dict[str, Character] = {}
        self.projects: Dict[str, Set[str]] = {}  # project_id -> set(character_names)

    def scan_all(self) -> Dict[str, Character]:
        """
        全盘扫描角色目录，返回所有角色对象
        """
        if not self.characters_dir.exists():
            logger.error(f"角色目录不存在: {self.characters_dir}")
            return {}

        for item in self.characters_dir.iterdir():
            if item.is_dir():
                char = Character(name=item.name, root_path=item)
                char.scan_photo()
                self.characters[char.name] = char
                logger.info(f"发现角色: {char.name}, 照片: {char.photo_path}")

        # 扫描每个角色的项目，建立项目-角色映射
        for char_name, char in self.characters.items():
            projects_dir = char.root_path / "projects"
            if not projects_dir.exists():
                continue
            for proj_dir in projects_dir.iterdir():
                if proj_dir.is_dir():
                    pid = proj_dir.name
                    self.projects.setdefault(pid, set()).add(char_name)
                    char.scan_project(pid)

        logger.info(f"扫描完成，共 {len(self.characters)} 个角色，"
                    f"发现项目: {list(self.projects.keys())}")
        return self.characters

    def get_common_projects(self) -> List[str]:
        """
        返回所有角色共同参与的项目ID列表
        （至少有两个角色的项目才被认为是多角色项目）
        """
        return [pid for pid, chars in self.projects.items() if len(chars) >= 1]

    def get_characters_for_project(self, project_id: str) -> Dict[str, Character]:
        """
        获取参与某个项目的所有角色
        """
        names = self.projects.get(project_id, set())
        return {n: self.characters[n] for n in names if n in self.characters}

    def find_log_file(self, project_id: str) -> Optional[Path]:
        """
        在所有参与该项目的角色目录中查找日志文件。
        优先级:
            1. 项目根目录（如有）
            2. 任一角色项目目录下的 sequence.json / sequence.txt / log.json
        """
        # 先尝试在项目公共根目录找（如果有的话，未来扩展）
        common_log = self.characters_dir / f"{project_id}_sequence.json"
        if common_log.exists():
            return common_log

        common_txt = self.characters_dir / f"{project_id}_sequence.txt"
        if common_txt.exists():
            return common_txt

        # 在角色项目目录中找
        for char_name in self.projects.get(project_id, []):
            proj_dir = self.characters_dir / char_name / "projects" / project_id
            if not proj_dir.exists():
                continue
            for cand in ["timeline.json", "sequence.json", "log.json", "sequence.txt"]:
                p = proj_dir / cand
                if p.exists():
                    return p

        return None

    def find_full_audio(self, project_id: str, hint_name: Optional[str] = None) -> Optional[Path]:
        """
        查找用户提供的完整合成音频文件。
        优先级:
            1. 日志中指定的文件名（hint_name）
            2. 常见名称: full_audio.*, combined.*, audio.*, merged.*
        """
        audio_exts = [".wav", ".mp3", ".aac", ".flac", ".m4a", ".ogg"]
        common_names = ["full_audio", "combined", "audio", "merged", "final_audio", "output"]

        # 1. 先按 hint 精确查找
        if hint_name:
            for char_name in self.projects.get(project_id, []):
                proj_dir = self.characters_dir / char_name / "projects" / project_id
                if not proj_dir.exists():
                    continue
                hint_path = proj_dir / hint_name
                if hint_path.exists():
                    return hint_path
                # 也尝试在角色根目录找
                hint_path2 = self.characters_dir / char_name / hint_name
                if hint_path2.exists():
                    return hint_path2

        # 2. 按常见名称搜索
        for char_name in self.projects.get(project_id, []):
            proj_dir = self.characters_dir / char_name / "projects" / project_id
            if not proj_dir.exists():
                continue
            for name in common_names:
                for ext in audio_exts:
                    cand = proj_dir / f"{name}{ext}"
                    if cand.exists():
                        return cand

        # 3. 最后按扩展名通配搜索（优先取 full_ 前缀的）
        for char_name in self.projects.get(project_id, []):
            proj_dir = self.characters_dir / char_name / "projects" / project_id
            if not proj_dir.exists():
                continue
            for ext in audio_exts:
                matches = sorted(proj_dir.glob(f"*{ext}"))
                for m in matches:
                    if "full" in m.stem.lower() or "combined" in m.stem.lower() or "merged" in m.stem.lower():
                        return m
                # 兜底：返回该目录下第一个音频（如果只有一个的话）
                if len(matches) == 1:
                    return matches[0]

        return None

