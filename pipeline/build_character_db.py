#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量构建角色人设数据库
为 audio_synthesis/character_profile/ 下的所有角色创建 personality.txt 和 suitable_roles.txt
"""

import os
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(PROJECT_ROOT, "audio_synthesis", "character_profile")
VIDEO_BASE = os.path.join(PROJECT_ROOT, "video_stitcher", "characters")

# ==================== 角色人设数据 ====================

CHARACTERS = {
    "W": {
        "personality": "中文叙事型声线，温柔沉稳，带有淡淡的感伤与回忆感。适合讲述长篇故事、校园爱情、青春回忆类内容。语气平实但富有情感层次，娓娓道来。",
        "suitable_roles": ["旁白/解说", "叙事型主角", "回忆杀", "情感故事", "青春校园"],
        "subtitle": {"color": "#E0E0E0", "stroke_color": "#222222", "bg_color": "#111111"}
    },
    "玉玉": {
        "personality": "中文生活吐槽类UP主风格，外号'雷霆语言'。接地气、幽默风趣、略带夸张。擅长吐槽日常生活琐事、社会现象，语气活泼有节奏感，偶尔带东北口音。",
        "suitable_roles": ["吐槽役", "搞笑担当", "生活杂谈", "吐槽", "整活", "单口相声"],
        "subtitle": {"color": "#FFD700", "stroke_color": "#332200", "bg_color": "#221100"}
    },
    "柊優花": {
        "personality": "日文VTuber风格，接橘雪莉声线。活泼可爱、元气满满，略带天然呆。语调轻快上扬，有偶像感。在B站和YouTube双平台活跃，常聊直播、粉丝互动、日常生活。",
        "suitable_roles": ["元气少女", "VTuber", "偶像", "可爱系", "日常聊天", "撒娇"],
        "subtitle": {"color": "#FFB6C1", "stroke_color": "#442233", "bg_color": "#221122"}
    },
    "希露菲成年版": {
        "personality": "《无职转生》希露菲叶特（成年），CV茅野爱衣。温柔治愈、人妻感满满，声线柔和温暖。对鲁迪乌斯深情专一，兼具坚强与柔弱。适合治愈系、温情对话。",
        "suitable_roles": ["治愈系", "人妻", "温柔女主", "治愈对话", "ASMR", "枕边话"],
        "subtitle": {"color": "#98FB98", "stroke_color": "#113311", "bg_color": "#0A220A"}
    },
    "希露菲青年版": {
        "personality": "《无职转生》希露菲叶特（青年期），CV茅野爱衣。活泼可爱、害羞内向，对鲁迪乌斯有着青梅竹马般的纯真感情。声线更稚嫩、更轻快，带有少女特有的羞涩。",
        "suitable_roles": ["青梅竹马", "害羞少女", "治愈系", "纯真对话", "青春校园"],
        "subtitle": {"color": "#90EE90", "stroke_color": "#113311", "bg_color": "#0A220A"}
    },
    "卡芙卡": {
        "personality": "《崩坏：星穹铁道》卡芙卡，星核猎手核心成员。神秘优雅、掌控人心，御姐气场全开。声线低沉魅惑，带着玩味与疏离。擅长心理博弈，言灵术操控人心。CV：徐慧（中）/伊藤静（日）。",
        "suitable_roles": ["御姐", "反派/灰色角色", "神秘系", "心理操控", "女王", "反派解说"],
        "subtitle": {"color": "#DDA0DD", "stroke_color": "#330033", "bg_color": "#220022"}
    },
    "洛琪希": {
        "personality": "《无职转生》洛琪希·米格路迪亚，鲁迪乌斯的师父。外表是萝莉但内心成熟，典型的'合法萝莉'。性格冷静理性但偶尔傲娇，声线清冷中带着温柔。魔法师设定，知识渊博。",
        "suitable_roles": ["师父/导师", "合法萝莉", "傲娇", "知性角色", "冷静吐槽", "魔法解说"],
        "subtitle": {"color": "#87CEEB", "stroke_color": "#001133", "bg_color": "#001122"}
    },
    "洛琪希2": {
        "personality": "《无职转生》洛琪希·米格路迪亚（备选模型）。与洛琪希相同人设：外表萝莉内心成熟，冷静理性略带傲娇，声线清冷温柔。魔法师、鲁迪乌斯师父。",
        "suitable_roles": ["师父/导师", "合法萝莉", "傲娇", "知性角色", "冷静吐槽", "魔法解说"],
        "subtitle": {"color": "#87CEFA", "stroke_color": "#001133", "bg_color": "#001122"}
    },
    "白菜": {
        "personality": "VTuber真白花音（眞白かのん），日本虚拟主播，B站活跃。设定为精灵国公主（王国沦陷后成为奴隶，为梦想奋斗）。声线甜美可爱、萝莉感强，自称'清楚系'。爱吃麦当劳、讨厌蔬菜。",
        "suitable_roles": ["萝莉", "可爱系", "精灵公主", "萌系", "清楚系", "撒娇", "治愈"],
        "subtitle": {"color": "#FFC0CB", "stroke_color": "#442233", "bg_color": "#221111"}
    },
    "知更鸟": {
        "personality": "《崩坏：星穹铁道》知更鸟（Robin），天环族歌姬。温柔治愈、心怀大爱，外柔内刚。声线清澈空灵、柔美神圣，如银河歌姬般具有透明感。以歌声抚慰伤痕、消弭纷争。CV：钱琛（中）/名冢佳织（日）。",
        "suitable_roles": ["歌姬", "治愈系", "圣女", "温柔女主", "天使", "歌声", "神圣系"],
        "subtitle": {"color": "#FFF8DC", "stroke_color": "#332211", "bg_color": "#221111"}
    },
    "管理员.B": {
        "personality": "系统管理员型角色，声线偏中性、冷静理性。语气平稳无波澜，带有一丝机械感但不失温度。适合规则说明、系统提示、理性分析类内容。",
        "suitable_roles": ["系统提示", "理性分析", "规则说明", "AI助手", "中性声线", "客观叙述"],
        "subtitle": {"color": "#00CED1", "stroke_color": "#002222", "bg_color": "#001111"}
    },
    "索尔": {
        "personality": "《罪恶装备》索尔·巴得凯，系列男主角。硬汉、热血、不羁，声线粗犷有力。被改造成生物兵器的第一人，原名佛莱迪克·布尔萨拉。战斗时狂野霸气，平时略带懒散。",
        "suitable_roles": ["硬汉", "热血男主", "战斗狂", "狂野", "大叔", "霸气", "格斗解说"],
        "subtitle": {"color": "#FF6347", "stroke_color": "#331100", "bg_color": "#221100"}
    },
    "艾尔黛拉": {
        "personality": "《明日方舟：终末地》艾尔黛拉（俗称'小羊'），六星自然属性干员。来自罗德岛的地质研究专家，温柔善良。声线柔和温暖，带有学者气质与治愈感。擅长治疗与辅助。",
        "suitable_roles": ["治疗师", "学者", "温柔系", "辅助", "治愈", "知性温柔"],
        "subtitle": {"color": "#F0E68C", "stroke_color": "#332200", "bg_color": "#221100"}
    },
    "认知进化": {
        "personality": "AI/科幻类角色，声线理性冷静，带有轻微电子感。语调平稳，用词精准。适合科技解说、哲学思辨、未来预测类内容。带有一种超越人类的智慧与疏离感。",
        "suitable_roles": ["AI解说", "科技评论", "哲学思辨", "未来预测", "理性分析", "系统 narrator"],
        "subtitle": {"color": "#7FFFD4", "stroke_color": "#002211", "bg_color": "#001111"}
    },
    "陈千语": {
        "personality": "中文女性角色，声线清亮有力，带有女侠/御姐气质。语气坚定果断，偶尔带有一丝冷幽默。适合古风、武侠、战斗类内容，也适合自信独立的女性角色。",
        "suitable_roles": ["女侠", "御姐", "战斗系", "古风", "武侠", "独立女性", "霸气女主"],
        "subtitle": {"color": "#FF8C00", "stroke_color": "#331100", "bg_color": "#221100"}
    },
}

# ==================== 执行 ====================

def create_files():
    for char_name, data in CHARACTERS.items():
        # 1. audio_synthesis 下的人设文件
        char_dir = os.path.join(BASE, char_name)
        if not os.path.exists(char_dir):
            print(f"[SKIP] 角色目录不存在: {char_name}")
            continue

        # personality.txt
        person_path = os.path.join(char_dir, "personality.txt")
        with open(person_path, "w", encoding="utf-8") as f:
            f.write(data["personality"])
        print(f"[OK] {char_name}/personality.txt")

        # suitable_roles.txt
        roles_path = os.path.join(char_dir, "suitable_roles.txt")
        with open(roles_path, "w", encoding="utf-8") as f:
            f.write("\n".join(data["suitable_roles"]))
        print(f"[OK] {char_name}/suitable_roles.txt")

        # 2. video_stitcher 下的字幕样式（创建目录和文件）
        video_char_dir = os.path.join(VIDEO_BASE, char_name, "profile")
        avatar_dir = os.path.join(video_char_dir, "avatar")
        os.makedirs(avatar_dir, exist_ok=True)

        style = {
            "color": data["subtitle"]["color"],
            "stroke_color": data["subtitle"]["stroke_color"],
            "stroke_width": 2,
            "bg_color": data["subtitle"]["bg_color"],
            "bg_padding": 8,
            "bg_radius": 6,
            "font_size": 42,
        }
        style_path = os.path.join(video_char_dir, "subtitle_style.json")
        with open(style_path, "w", encoding="utf-8") as f:
            json.dump(style, f, ensure_ascii=False, indent=2)
        print(f"[OK] video_stitcher/{char_name}/profile/subtitle_style.json")

    print("\n全部完成！")


if __name__ == "__main__":
    create_files()
