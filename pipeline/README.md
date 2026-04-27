# AIBLI 自动化流水线调度器

一站式串联：文案处理 → 音频合成(GPT-SoVITS) → 视频合成(Video Stitcher) → B站上传

## 快速开始

### 1. 启动 GUI 面板（推荐）

双击 `run_gui.bat`

界面功能：
- 左侧：项目队列实时状态（带颜色区分）
- 右侧：滚动执行日志
- 底部：控制按钮（启动/停止、重试、跳过、打开输出目录）

### 2. 添加任务

**方式A：丢文件**
把文案 `.txt` 或截图图片丢进 `queue/pending/` 文件夹，调度器自动扫描并处理。

**方式B：GUI添加**
点击 "+ 添加文案" 按钮选择文件。

### 3. 启动调度

点击 "▶ 启动调度"，后台开始按顺序处理：

```
文案转换 → 音频合成 → 视频合成 → [可选] B站上传
```

每一步完成后自动进入下一步，失败自动重试（最多2次）。

### 4. 取结果

最终视频输出到 `output/` 目录。

---

## 目录结构

```
D:\AIBLI\pipeline\
├── pipeline_orchestrator.py    # 核心调度器
├── pipeline_gui.py             # GUI面板
├── character_mapper.py         # 角色映射（预留人设接口）
├── pipeline_config.json        # 配置文件
├── run_gui.bat                 # 启动GUI
├── run_cli.bat                 # 启动命令行
├── queue\
│   ├── pending\                # 待处理文件放这里
│   └── done\                  # 处理完的源文件移到这里
├── projects\                   # 项目工作区
├── output\                     # 最终视频输出
└── logs\                       # 执行日志
```

---

## 文案格式

### 标准格式（音频端直接识别）
```
[A] 大家好，欢迎收看本期节目
[B] 我是吐槽役，今天来吐槽一下
[A] 首先我们来看看第一条新闻
```

### 分段格式（我们之前的输出，自动转换）
```
1（第1段）
----
台词内容...

2（第2段）
----
台词内容...
```

### 对话格式
```
小傻: 本人有幸喝过一次蜜雪冰城...
炖汤喝纯奶: 能简单描述一下吗？...
```

---

## 配置说明

编辑 `pipeline_config.json`：

| 字段 | 说明 |
|------|------|
| `paths.python_runtime` | GPT-SoVITS 的 Python 路径 |
| `paths.audio_synthesis_base` | 音频合成端目录 |
| `paths.video_stitcher_base` | 视频合成端目录 |
| `paths.bili_uploader_base` | B站上传脚本目录（可选） |
| `pipeline.auto_start` | 启动时是否自动开始调度 |
| `pipeline.max_retries` | 失败重试次数 |
| `pipeline.enable_bili_upload` | 是否启用B站上传 |
| `audio_params` | GPT-SoVITS 参数（top_k/top_p/temperature/speed/pause） |

---

## 链路流程

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────┐
│ queue/      │ ──▶ │ 文案转换      │ ──▶ │ GPT-SoVITS   │ ──▶ │ Video       │
│ pending/    │     │ (script.txt) │     │ 配音         │     │ Stitcher    │
└─────────────┘     └──────────────┘     └──────────────┘     └─────────────┘
                                                                    │
                                                                    ▼
                                                            ┌─────────────┐
                                                            │ output/     │
                                                            │ .mp4        │
                                                            └─────────────┘
```

---

## 注意事项

1. **音频端必须先配置好角色**：`audio_synthesis/character_profile/` 下至少要有两个角色（A 和 B），包含模型权重、参考音频、参考文本。
2. **视频端必须先放角色照片**：`video_stitcher/characters/A/` 和 `characters/B/` 下要有 avatar 照片。
3. **图片源暂不支持自动OCR**：请先手动转成 txt 文案再丢进队列。后续会接入图像识别。
4. **B站上传暂未接入**：等你的 BiliAutoUpload 脚本接口标准化后再连上。

---

## 扩展计划

- [ ] 接入图像OCR，截图直接丢进来
- [ ] 角色人设智能匹配（根据台词内容分配合适的配音角色）
- [ ] B站上传自动对接
- [ ] 邮件/微信通知（任务完成/失败）
