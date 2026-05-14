# Project Manifest 项目文档规范

## 概述

`project_manifest.json` 是音频合成端 → 视频合成端的**交接文档**。
音频合成端完成配音后，生成此文件放入项目输出目录，视频合成端读取后自动执行。

## 文件位置

```
<audio_synthesis>/project_output/{project_id}/
├── project_manifest.json    ← 项目文档（本规范）
├── merged.wav               ← 完整合成音频
├── timeline.json            ← 时间轴（含字幕文本）
├── dialogue_order.txt       ← 口播稿（冗余参考）
└── sequence_log.txt         ← 顺序日志（冗余参考）
```

## Schema

```json
{
  "version": "1.0",
  "project_id": "P001_项目名称",
  "status": "ready_for_video",
  "created_at": "2026-04-27T10:30:00",
  "source": {
    "type": "dialogue_script",
    "script_id": "SCRIPT_001"
  },
  "characters": {
    "A": {
      "name": "柊優花",
      "lang": "日文",
      "voice_model": "yuka_v2"
    },
    "B": {
      "name": "玉玉",
      "lang": "中文",
      "voice_model": "yuyu_v1"
    }
  },
  "audio": {
    "merged_file": "merged.wav",
    "total_duration_sec": 118.78,
    "pause_between_clips_sec": 0.3
  },
  "timeline_file": "timeline.json",
  "video_config": {
    "resolution": "auto",
    "fps": 24,
    "subtitle_enabled": true,
    "subtitle_config": "default"
  },
  "output": {
    "target_dir": "./output",
    "filename": "P001_项目名称.mp4"
  }
}
```

## 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `version` | string | 是 | 文档版本，当前 `"1.0"` |
| `project_id` | string | 是 | 项目唯一标识 |
| `status` | string | 是 | 项目状态：`ready_for_video` / `processing` / `completed` / `error` |
| `created_at` | string | 是 | ISO 8601 时间戳 |
| `source` | object | 否 | 来源信息（文案脚本ID等） |
| `characters` | object | 是 | 角色映射表，key 为角色ID（与 timeline.json 中 `char` 对应），value 含 `name`/`lang`/`voice_model` |
| `audio.merged_file` | string | 是 | 完整合成音频文件名 |
| `audio.total_duration_sec` | float | 是 | 音频总时长（秒） |
| `audio.pause_between_clips_sec` | float | 否 | 片段间停顿（秒） |
| `timeline_file` | string | 是 | 时间轴文件名（相对路径） |
| `video_config.resolution` | string | 否 | `"auto"` 自动推断，或 `"1080,1920"` / `"1920,1080"` |
| `video_config.fps` | int | 否 | 帧率，默认 24 |
| `video_config.subtitle_enabled` | bool | 否 | 是否启用字幕，默认 true |
| `video_config.subtitle_config` | string | 否 | 字幕配置：`"default"` 或自定义路径 |
| `output.target_dir` | string | 否 | 输出目录，默认 video_stitcher/output |
| `output.filename` | string | 否 | 输出文件名，默认 `{project_id}.mp4` |

## 状态流转

```
ready_for_video ──→ processing ──→ completed
                        │
                        └──→ error
```

- **音频合成端**生成文档时设置 `status: "ready_for_video"`
- **视频合成端**开始处理时更新为 `status: "processing"`
- **完成后**更新为 `status: "completed"`
- **出错时**更新为 `status: "error"` 并写入 `error_message`

## 向后兼容

如果目录下只有 `timeline.json` + `merged.wav` 而没有 `project_manifest.json`，
视频合成端仍按旧桥梁模式处理，自动推断 project_id 为目录名。
