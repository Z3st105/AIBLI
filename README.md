# AIBLI

基于 GPT-SoVITS 与 MoviePy 的虚拟角色音视频合成管线。

## 项目简介

AIBLI 是一套将虚拟角色对话合成为带字幕短视频的自动化工具，包含两个核心模块：

- **audio_synthesis** — 基于 GPT-SoVITS 的语音合成管线，负责将剧本文本转换为多角色对话音频
- **video_stitcher** — 基于 MoviePy 2.x 的视频合成工具，将角色立绘、音频与字幕合成为竖屏短视频（1080x1920）

## 目录结构

```
AIBLI/
├── audio_synthesis/          # 语音合成管线
│   ├── audio_synthesis_pipeline.py  # 主入口
│   ├── character_profile/    # 角色配置（人设文本、参考音频等，不上传）
│   ├── engine/               # GPT-SoVITS 引擎（外部依赖，不上传）
│   ├── project_output/       # 生成音频输出（不上传）
│   ├── scripts/              # 剧本文件
│   └── README.md             # 音频模块说明
├── pipeline/                 # 桥接文件/中间产物
├── video_stitcher/           # 视频合成工具
│   ├── src/                  # 核心源码
│   │   ├── main.py           # 主程序
│   │   ├── core/             # 视频/字幕/音频混合核心
│   │   └── utils/            # 工具函数
│   ├── characters/           # 角色配置（字幕样式等）
│   ├── output/               # 生成视频输出（不上传）
│   ├── docs/                 # 文档
│   ├── requirements.txt      # Python 依赖
│   └── README.md             # 视频模块说明
└── README.md                 # 本文件
```

## 依赖说明

本项目依赖以下外部工具，**无需上传至本仓库**，请按官方文档自行安装：

| 依赖 | 用途 | 官方仓库 |
|------|------|---------|
| **GPT-SoVITS** | 语音合成引擎 | [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) |
| **MoviePy 2.x** | 视频合成 | [Zulko/moviepy](https://github.com/Zulko/moviepy) |
| **Python 3.9+** | 运行时 | — |

### audio_synthesis 模块

将 `GPT-SoVITS` 引擎放置于 `audio_synthesis/engine/` 目录下，确保目录结构如下：

```
audio_synthesis/engine/
├── GPT_SoVITS/          # GPT-SoVITS 源码
├── runtime/             # Python 运行环境（可选，也可使用系统 Python）
├── tools/               # 辅助工具
└── ...
```

角色配置文件放置于 `audio_synthesis/character_profile/{角色名}/` 目录下，包含：
- `personality.txt` — 角色人设描述
- `ref_audio/sample.wav` — 参考音频样本
- `{角色名}.ckpt` / `{角色名}.pth` — 训练好的角色模型权重

### video_stitcher 模块

```bash
cd video_stitcher
pip install -r requirements.txt
python src/main.py
```

角色配置放置于 `video_stitcher/characters/{角色名}/profile/` 目录下，包含：
- `subtitle_style.json` — 字幕样式配置
- `avatar/photo.png` — 角色立绘（封面用）

## 工作流程

1. **准备剧本** — 在 `audio_synthesis/scripts/` 下编写对话剧本
2. **语音合成** — 运行 `audio_synthesis` 管线，生成各角色音频
3. **时间线生成** — 音频管线输出 `timeline.json` 与合并后的音频
4. **视频合成** — `video_stitcher` 读取时间线，合成带字幕的竖屏视频

## 协作模式

本项目与音频合成团队采用**桥接模式**集成：
- 音频团队负责 `audio_synthesis` 模块的输出
- 视频团队负责读取 `timeline.json` 并驱动 `video_stitcher`
- 双方通过统一的 `timeline.json` 格式进行数据交换

## 注意事项

- 本项目仓库**仅包含源码与配置模板**，不含模型权重、运行时环境与生成产物
- 角色素材（头像、模型、参考音频）请按项目目录结构自行准备
- 视频输出为竖屏 9:16 格式（1080x1920），采用封面缩放模式以最小化黑边

## License

MIT
