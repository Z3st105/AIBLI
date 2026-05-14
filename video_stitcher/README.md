# Video Stitcher — 多角色音画同步视频拼接器

## 功能概述

本工具用于将**多角色的静态照片**与**配音音轨**合成为一段完整的视频。
核心能力：
- **桥梁模式**：直接对接音频合成部门的输出目录，无需手动复制文件
- **双模式自动检测**：根据日志内容自动识别"顺序拼接"或"时间戳切镜"
- **分辨率自动推断**：根据角色照片比例自动选择竖屏/横屏
- **字幕系统**：每段台词自动打字幕，支持角色独立配色
- **画面随声切换**：当前谁在说话，画面就显示谁的照片
- **间隙自动填充**：说话间隙默认延续上一个角色的画面
- **一键 Web 服务**：本地浏览器操作，双击 `start.bat` 启动

---

## 目录结构

```
video_stitcher/
├── src\                         # 源代码
│   ├── main.py                  # 主入口（命令行）
│   ├── web_server.py            # Web 服务入口
│   ├── models\
│   │   ├── character.py         # 角色实体
│   │   └── timeline.py          # 时间轴片段
│   └── core\
│       ├── project_scanner.py   # 角色/项目扫描
│       ├── log_parser.py        # 日志解析
│       ├── audio_mixer.py       # 音频处理
│       ├── video_builder.py     # 视频合成
│       └── subtitle_renderer.py # 字幕渲染（Pillow）
│
├── characters\                  # 【角色数据目录】
│   └── A\                       # 角色A
│       ├── profile\
│       │   ├── avatar\          # ★ 角色照片放这里
│       │   │   └── photo.png
│       │   └── subtitle_style.json  # 字幕样式（可选，覆盖全局）
│       └── photos\              # 兼容旧结构（次优先）
│
├── output\                      # 输出目录（自动生成）
├── subtitle_config.json         # 全局默认字幕样式
├── start.bat                    # ★ 双击启动 Web 服务
├── run.bat                      # 命令行快速运行
├── install.bat                  # 安装依赖
└── requirements.txt
```

---

## 快速上手（桥梁模式，推荐）

**前提**：音频合成部门的输出目录结构如下：
```
audio_synthesis/project_output/{project_id}/
├── merged.wav        # 完整合成音频
├── timeline.json     # 时间轴（含 char/start_sec/end_sec/text/lang）
├── dialogue_order.txt
└── sequence_log.txt
```

**命令行方式：**
```bash
python src/main.py --project P001 --source-dir "../audio_synthesis/project_output/P001"
```

**Web 界面方式：**
1. 双击 `start.bat`，浏览器自动打开 http://127.0.0.1:5000
2. 填入"前端输出目录"路径和"项目ID"
3. 点击"开始生成视频"，完成后直接下载

---

## 角色设置

每个角色在 `characters/` 下有独立文件夹：

```
characters/
└── 角色名/                         # 文件夹名 = 角色ID（与 timeline.json 中 char 字段对应）
    └── profile/
        ├── avatar/                 # ★ 照片放这里（jpg/png/webp）
        │   └── photo.png
        └── subtitle_style.json     # 可选：角色专属字幕配色
```

**字幕样式示例（`subtitle_style.json`）：**
```json
{
  "color": "#A8E6FF",
  "bg_color": "#CC001122",
  "stroke_color": "#003355",
  "font_size": 44
}
```
未配置时自动使用 `subtitle_config.json` 全局默认值。

---

## 两种工作模式

| 模式 | 输入 | 适用场景 |
|------|------|----------|
| **时间戳模式** (timestamp) ★ | 完整合成音频 + timeline.json | 音频合成部门已输出完整音轨和时间轴 |
| **顺序模式** (sequence) | 零散音频 + sequence.json | 零散音频按顺序拼接 |

程序根据日志内容**自动判断**，无需手动切换。

---

## 命令行参数

```bash
python src/main.py \
  --project P001 \                      # 项目ID（必填）
  --source-dir "../audio_synthesis/project_output/P001" \  # 前端输出目录（桥梁模式）
  --output "./output/P001.mp4" \       # 输出路径（可选）
  --width 1080 --height 1920 \          # 分辨率（不填则自动推断）
  --fps 24 \                            # 帧率（默认24）
  --subtitle-config subtitle_config.json  # 字幕配置（默认项目根目录）
```

---

## 分辨率策略

| 照片比例 | 自动推断结果 |
|----------|-------------|
| 竖向（h > w×1.1） | **1080×1920**（短视频竖屏）|
| 横向（w > h×1.1） | **1920×1080**（横屏）|
| 正方形 / 未知 | **1080×1920**（默认竖屏）|

---

## 注意事项

1. **照片路径**：优先读 `profile/avatar/`，其次 `photos/`，最后角色根目录
2. **角色ID**：文件夹名需与 `timeline.json` 中 `char` 字段严格匹配
3. **音频格式**：支持 `wav`, `mp3`, `aac`, `flac`, `m4a`, `ogg`
4. **图片填充**：cover 模式（等比放大 + 居中裁剪），无黑边不变形

---

## License

内部工具，自由使用。
