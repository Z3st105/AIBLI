# AIBLI 多引擎 TTS 架构

## 概述

AIBLI 现在支持多个 TTS 引擎，可以在 Fish Speech 和 GPT-SoVITS 之间灵活切换。

## 支持的引擎

| 引擎 | 版本 | 特点 | 采样率 |
|------|------|------|--------|
| Fish Speech | 1.5 | 轻量级，推理快，适合实时场景 | 44100 Hz |
| GPT-SoVITS | v2Pro | 高质量，支持多版本权重 | 32000 Hz |

## 文件结构

```
audio_synthesis/
├── engine/
│   ├── __init__.py
│   ├── tts_engine_base.py      # TTS 引擎抽象基类
│   ├── fish_speech_engine.py   # Fish Speech 适配器
│   ├── gpt_sovits_engine.py    # GPT-SoVITS 适配器
│   └── engine_manager.py       # 引擎管理器
├── character_profile/          # 角色配置目录
│   └── 角色名/
│       ├── profile.json
│       ├── ref_audio/
│       ├── ref_text.txt
│       ├── ref_lang.txt
│       └── engine_preference.txt  # 可选：指定该角色使用的引擎
├── audio_synthesis_pipeline.py      # 原版 pipeline (仅 GPT-SoVITS)
├── audio_synthesis_pipeline_v2.py   # 新版 pipeline (多引擎)
└── test_fish_speech.py              # Fish Speech 测试脚本
```

## 使用方法

### 1. 使用 Fish Speech (默认)

```bash
python audio_synthesis_pipeline_v2.py \
    --project P111 \
    --script "project_input/P111_script.txt" \
    --engine fish_speech
```

### 2. 使用 GPT-SoVITS

```bash
python audio_synthesis_pipeline_v2.py \
    --project P111 \
    --script "project_input/P111_script.txt" \
    --engine gpt_sovits
```

### 3. 加载所有引擎

```bash
python audio_synthesis_pipeline_v2.py \
    --project P111 \
    --script "project_input/P111_script.txt" \
    --engine all
```

### 4. 强制使用指定引擎

```bash
# 强制所有句子使用 Fish Speech，忽略角色偏好
python audio_synthesis_pipeline_v2.py \
    --project P111 \
    --script "project_input/P111_script.txt" \
    --force_engine fish_speech
```

### 5. 文案中指定引擎

在文案中可以用 `@引擎名` 指定单句使用的引擎：

```
[A] 这句用默认引擎
[A@fish_speech] 这句用 Fish Speech
[B@gpt_sovits] 这句用 GPT-SoVITS
```

### 6. 为角色设置默认引擎

在角色目录下创建 `engine_preference.txt`：

```bash
# character_profile/知更鸟/engine_preference.txt
fish_speech
```

可选值：`fish_speech`、`gpt_sovits`（留空则使用全局默认）

## 测试

```bash
# 测试 Fish Speech 引擎
python test_fish_speech.py
```

## API 参考

### TTSEngineBase

所有引擎的基类，定义了统一接口：

```python
class TTSEngineBase(ABC):
    @property
    def engine_name(self) -> str: ...

    @property
    def sample_rate(self) -> int: ...

    def load_model(self, model_path: str, **kwargs) -> None: ...

    def synthesize(
        self,
        text: str,
        voice_profile: CharacterVoiceProfile,
        config: TTSConfig,
    ) -> Optional[np.ndarray]: ...

    def is_loaded(self) -> bool: ...

    def unload(self) -> None: ...
```

### EngineManager

引擎管理器，负责引擎选择和切换：

```python
manager = EngineManager(default_engine="fish_speech")
manager.register_engine(fish_engine)
manager.register_engine(gpt_engine)
manager.load_engine("fish_speech")

# 合成
audio = manager.synthesize(text, voice_profile, config)
```

### CharacterVoiceProfile

角色语音配置：

```python
@dataclass
class CharacterVoiceProfile:
    char_id: str
    name: str
    ref_audio_path: str
    ref_text: str
    ref_lang: str = "中文"
    engine_preference: Optional[str] = None
    extra_params: Optional[dict] = None
```

## 注意事项

1. **参考音频**：Fish Speech 和 GPT-SoVITS 都需要参考音频来进行声音克隆
2. **参考文本**：参考音频对应的文本必须准确，影响合成质量
3. **采样率差异**：Fish Speech 输出 44100 Hz，GPT-SoVITS 输出 32000 Hz，拼接时需注意
4. **GPU 内存**：同时加载两个引擎需要更多 GPU 内存

## 故障排除

### Fish Speech 加载失败

检查：
- `D:\fish-speech\checkpoints\fish-speech-1.5` 目录是否存在
- GPU 是否可用（CUDA）
- Python 依赖是否安装完整

### GPT-SoVITS 加载失败

检查：
- `engine/GPT_SoVITS` 目录是否存在
- 权重文件是否在正确位置
- runtime 环境是否配置正确
