#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
角色映射器 — 负责将匿名对话角色映射到音频端的实际角色(A/B/C...)

当前模式: 顺序映射（按出现顺序分配A/B）
未来扩展: 基于人设内容的智能匹配
"""

import os
import json
import re
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class CharacterProfile:
    """角色人设数据结构"""
    char_id: str           # 音频端标识，如 "A"
    name: str              # 显示名，如 "柊優花"
    folder_name: str       # 文件夹名
    personality: str = ""  # 性格描述
    voice_type: str = ""   # 声线特点
    suitable_roles: List[str] = None  # 适合配什么类型台词
    ref_lang: str = "中文"

    def __post_init__(self):
        if self.suitable_roles is None:
            self.suitable_roles = []


class CharacterMapper:
    """
    角色映射器
    ========
    功能：
    1. 扫描 character_profile/ 加载所有人设
    2. 根据策略将匿名角色映射到实际音频角色
    3. 预留智能匹配接口（等后面人设完善后实现）
    """

    def __init__(self, profile_dir: str):
        self.profile_dir = profile_dir
        self.profiles: Dict[str, CharacterProfile] = {}  # char_id -> profile
        self._load_profiles()

    def _load_profiles(self):
        """扫描音频端的 character_profile 目录加载人设"""
        if not os.path.exists(self.profile_dir):
            return

        for folder in sorted(os.listdir(self.profile_dir)):
            folder_path = os.path.join(self.profile_dir, folder)
            if not os.path.isdir(folder_path):
                continue

            # 读取 alias.txt 获取音频端标识
            alias = folder
            alias_path = os.path.join(folder_path, "alias.txt")
            if os.path.exists(alias_path):
                with open(alias_path, "r", encoding="utf-8") as f:
                    alias = f.read().strip().lstrip("\ufeff") or folder

            # 读取 ref_lang.txt
            lang = "中文"
            lang_path = os.path.join(folder_path, "ref_lang.txt")
            if os.path.exists(lang_path):
                with open(lang_path, "r", encoding="utf-8") as f:
                    lang = f.read().strip().lstrip("\ufeff") or "中文"

            # 读取人设描述（预留，目前可能没有）
            personality = ""
            person_path = os.path.join(folder_path, "personality.txt")
            if os.path.exists(person_path):
                with open(person_path, "r", encoding="utf-8") as f:
                    personality = f.read().strip()

            # 读取适合的角色类型（预留）
            suitable = []
            roles_path = os.path.join(folder_path, "suitable_roles.txt")
            if os.path.exists(roles_path):
                with open(roles_path, "r", encoding="utf-8") as f:
                    suitable = [line.strip() for line in f if line.strip()]

            profile = CharacterProfile(
                char_id=alias,
                name=folder,
                folder_name=folder,
                personality=personality,
                voice_type="",
                suitable_roles=suitable,
                ref_lang=lang,
            )
            self.profiles[alias] = profile

    # ==================== 映射策略 ====================

    def map_sequential(self, speakers: List[str]) -> Dict[str, str]:
        """
        顺序映射策略：按出现顺序分配 A, B, C...
        最简单可靠，适合人设还没完善时使用
        """
        sorted_aliases = sorted(self.profiles.keys())
        mapping = {}
        for idx, speaker in enumerate(speakers):
            if idx < len(sorted_aliases):
                mapping[speaker] = sorted_aliases[idx]
            else:
                # 角色不够，循环复用最后一个
                mapping[speaker] = sorted_aliases[-1] if sorted_aliases else "A"
        return mapping

    def map_by_content(self, dialogues: List[tuple]) -> Dict[str, str]:
        """
        内容匹配策略：根据台词内容判断适合哪个角色（预留接口）

        dialogues: [(speaker_id, text), ...]
        返回: {speaker_id: char_alias}

        TODO: 等人设文件完善后实现：
        - 分析台词情绪（吐槽/正经/可爱/暴躁...）
        - 匹配角色 personality 和 suitable_roles
        - 返回最优映射
        """
        # 目前 fallback 到顺序映射
        speakers = list(dict.fromkeys([spk for spk, _ in dialogues]))
        return self.map_sequential(speakers)

    def map_with_hint(self, speakers: List[str], hint: Dict[str, str]) -> Dict[str, str]:
        """
        带提示的映射：用户手动指定某些角色配谁
        hint: {"小傻": "A", "末老先登": "B"}
        未指定的 fallback 到顺序映射
        """
        mapping = {}
        remaining = []
        for spk in speakers:
            if spk in hint:
                mapping[spk] = hint[spk]
            else:
                remaining.append(spk)

        # 剩余角色顺序映射（跳过已被占用的alias）
        used_aliases = set(mapping.values())
        sorted_aliases = [a for a in sorted(self.profiles.keys()) if a not in used_aliases]
        for idx, spk in enumerate(remaining):
            if idx < len(sorted_aliases):
                mapping[spk] = sorted_aliases[idx]
            else:
                mapping[spk] = sorted_aliases[-1] if sorted_aliases else "A"
        return mapping

    # ==================== 工具方法 ====================

    def get_available_chars(self) -> List[str]:
        """返回所有可用的角色标识列表"""
        return sorted(self.profiles.keys())

    def get_profile(self, char_id: str) -> Optional[CharacterProfile]:
        """获取指定角色的人设"""
        return self.profiles.get(char_id)

    def format_hint_file(self) -> str:
        """
        生成一个角色映射提示模板文件内容
        用户可以填这个文件来手动指定映射关系
        """
        lines = ["# 角色映射提示文件", "# 格式: 截图里的名字 = 音频角色标识", "# 可用音频角色: " + ", ".join(self.get_available_chars()), ""]
        for alias, profile in sorted(self.profiles.items()):
            lines.append(f"# {alias} = {profile.name} ({profile.personality or '暂无描述'})")
        lines.append("")
        lines.append("# 示例（删掉#启用）:")
        lines.append("# 小傻 = A")
        lines.append("# 末老先登 = B")
        return "\n".join(lines)


# ==================== 快捷函数 ====================

def create_mapper_from_config(config_path: str = "pipeline_config.json") -> CharacterMapper:
    """从配置文件创建映射器"""
    import json as _json
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = _json.load(f)
    profile_dir = cfg.get("character_mapping", {}).get("profile_dir", "D:\\AIBLI\\audio_synthesis\\character_profile")
    return CharacterMapper(profile_dir)


# ==================== 测试入口 ====================

if __name__ == "__main__":
    mapper = create_mapper_from_config()
    print("可用角色:", mapper.get_available_chars())
    for cid in mapper.get_available_chars():
        p = mapper.get_profile(cid)
        print(f"  {cid}: {p.name} | 语言: {p.ref_lang} | 人设: {p.personality or '无'}")

    # 测试顺序映射
    speakers = ["钖", "末老先登", "小傻"]
    mapping = mapper.map_sequential(speakers)
    print("\n顺序映射结果:")
    for spk, alias in mapping.items():
        print(f"  {spk} -> {alias}")
