#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIBLI 流水线调度器 — 串联文案→音频→视频→上传的完整自动化链路

用法:
    python pipeline_orchestrator.py              # 命令行模式
    python pipeline_gui.py                       # GUI模式
"""

import os
import sys
import re
import json
import time
import shutil
import subprocess
import threading
import traceback
from datetime import datetime
from pathlib import Path
from enum import Enum, auto
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Callable

# ==================== 常量与配置 ====================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "pipeline_config.json")


class Status(Enum):
    PENDING = "等待中"
    SCRIPT_CONVERTING = "文案转换中"
    SCRIPT_READY = "文案就绪"
    AUDIO_SYNTHESIZING = "音频合成中"
    AUDIO_DONE = "音频完成"
    VIDEO_SYNTHESIZING = "视频合成中"
    VIDEO_DONE = "视频完成"
    BILI_UPLOADING = "B站上传中"
    COMPLETED = "已完成"
    FAILED = "失败"
    RETRYING = "重试中"


STEP_ORDER = [
    Status.SCRIPT_CONVERTING,
    Status.AUDIO_SYNTHESIZING,
    Status.VIDEO_SYNTHESIZING,
]


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ==================== 项目数据类 ====================

@dataclass
class Project:
    project_id: str
    source_file: str
    status: Status = Status.PENDING
    step: str = ""
    created_at: str = ""
    updated_at: str = ""
    error_msg: str = ""
    retry_count: int = 0
    output_video: str = ""
    script_path: str = ""
    audio_output_dir: str = ""

    def to_dict(self):
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @staticmethod
    def from_dict(d: dict):
        d = dict(d)
        d["status"] = Status(d.get("status", "等待中"))
        return Project(**d)


# ==================== 日志系统 ====================

class PipelineLogger:
    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._listeners: List[Callable] = []
        self._lock = threading.Lock()
        today = datetime.now().strftime("%Y-%m-%d")
        self.log_file = os.path.join(log_dir, f"{today}.log")

    def add_listener(self, callback: Callable):
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable):
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def log(self, level: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        with self._lock:
            # 写文件
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            # 通知监听器
            for cb in list(self._listeners):
                try:
                    cb(level, msg)
                except Exception:
                    pass
        print(line)

    def info(self, msg: str):
        self.log("INFO", msg)

    def error(self, msg: str):
        self.log("ERROR", msg)

    def warn(self, msg: str):
        self.log("WARN", msg)

    def success(self, msg: str):
        self.log("SUCCESS", msg)


# ==================== 核心调度器 ====================

class PipelineOrchestrator:
    def __init__(self, config: dict, logger: PipelineLogger):
        self.cfg = config
        self.logger = logger
        self.paths = config["paths"]
        self.pipeline_cfg = config["pipeline"]

        self.projects: Dict[str, Project] = {}
        self._lock = threading.Lock()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._callbacks: List[Callable] = []  # 状态变更回调

        # 路径快捷方式
        self.queue_pending = os.path.join(self.paths["queue_dir"], "pending")
        self.queue_done = os.path.join(self.paths["queue_dir"], "done")
        self.projects_dir = self.paths["projects_dir"]
        self.final_output = self.paths["final_output_dir"]
        self.audio_base = self.paths["audio_synthesis_base"]
        self.video_base = self.paths["video_stitcher_base"]

        os.makedirs(self.queue_pending, exist_ok=True)
        os.makedirs(self.queue_done, exist_ok=True)
        os.makedirs(self.projects_dir, exist_ok=True)
        os.makedirs(self.final_output, exist_ok=True)

        # 加载已完成的文件列表（防止重启后重复处理）
        self._done_files: set = set()
        if os.path.exists(self.queue_done):
            for name in os.listdir(self.queue_done):
                self._done_files.add(name)

        # 加载角色映射器（用于查询音频端实际可用的角色标识）
        profile_dir = config.get("character_mapping", {}).get("profile_dir",
            os.path.join(self.audio_base, "character_profile"))
        try:
            from character_mapper import CharacterMapper
            self.char_mapper = CharacterMapper(profile_dir)
            scanned_chars = self.char_mapper.get_available_chars()

            # 优先使用配置中的 default_char_order，过滤掉不存在的
            configured_order = config.get("character_mapping", {}).get("default_char_order", [])
            valid_configured = [c for c in configured_order if c in scanned_chars]
            remaining = [c for c in scanned_chars if c not in valid_configured]
            self.available_chars = valid_configured + remaining

            self.logger.info(f"[角色映射] 已加载 {len(self.available_chars)} 个角色")
            self.logger.info(f"[角色映射] 默认顺序: {', '.join(self.available_chars[:5])}{'...' if len(self.available_chars) > 5 else ''}")
        except Exception as e:
            self.logger.warn(f"[角色映射] 加载失败: {e}，将使用默认 A/B")
            self.char_mapper = None
            self.available_chars = ["A", "B"]

    # ---------- 回调 ----------

    def add_callback(self, cb: Callable):
        self._callbacks.append(cb)

    def _notify(self, project: Project):
        for cb in list(self._callbacks):
            try:
                cb(project)
            except Exception:
                pass

    def _update_status(self, project: Project, status: Status, step: str = "", error: str = ""):
        with self._lock:
            project.status = status
            project.step = step or status.value
            project.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if error:
                project.error_msg = error
            else:
                project.error_msg = ""
        self._notify(project)
        self.logger.info(f"[{project.project_id}] {status.value} | {step}")

    # ---------- 项目管理 ----------

    def scan_queue(self) -> List[str]:
        """扫描待处理队列，返回文件列表"""
        files = []
        if not os.path.exists(self.queue_pending):
            return files
        for name in sorted(os.listdir(self.queue_pending)):
            path = os.path.join(self.queue_pending, name)
            if os.path.isfile(path):
                files.append(path)
        return files

    def create_project(self, source_file: str) -> Optional[Project]:
        """从源文件创建新项目"""
        basename = os.path.basename(source_file)
        if basename in self._done_files:
            self.logger.info(f"跳过已完成的文件: {basename}")
            return None

        ext = os.path.splitext(source_file)[1].lower()
        # 支持 txt（文案）和图片（截图）
        if ext not in (".txt", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"):
            self.logger.warn(f"不支持的文件类型: {source_file}")
            return None

        pid = self._next_project_id()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        proj = Project(
            project_id=pid,
            source_file=source_file,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self.projects[pid] = proj
        self.logger.info(f"创建项目 {pid} | 来源: {os.path.basename(source_file)}")
        self._notify(proj)
        return proj

    def _next_project_id(self) -> str:
        """生成下一个项目ID: P001, P002..."""
        with self._lock:
            if not self.projects:
                max_num = 0
            else:
                max_num = max(int(k[1:]) for k in self.projects.keys() if k.startswith("P") and k[1:].isdigit())
        # 也检查硬盘上已有的项目
        for name in os.listdir(self.projects_dir):
            if name.startswith("P") and name[1:].isdigit():
                max_num = max(max_num, int(name[1:]))
        return f"P{max_num + 1:03d}"

    # ---------- 流水线执行 ----------

    def start(self):
        """启动后台调度线程"""
        if self._running:
            self.logger.warn("调度器已在运行")
            return
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        self.logger.info("调度器已启动")

    def stop(self):
        """停止调度"""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        self.logger.info("调度器已停止")

    def _worker_loop(self):
        """后台工作循环"""
        while self._running:
            try:
                # 1. 扫描新文件
                pending_files = self.scan_queue()
                for fpath in pending_files:
                    basename = os.path.basename(fpath)
                    # 检查是否已完成（重启后从 done 目录加载的防重）
                    if basename in self._done_files:
                        continue
                    # 检查是否已有对应项目（任何状态都防重，避免失败项目重复创建）
                    already = any(p.source_file == fpath for p in self.projects.values())
                    if not already:
                        self.create_project(fpath)

                # 2. 找下一个可执行的项目（等待中的）
                proj = self._pick_next_project()
                if proj:
                    self._run_project(proj)
                else:
                    time.sleep(2)

            except Exception as e:
                self.logger.error(f"工作循环异常: {e}")
                traceback.print_exc()
                time.sleep(5)

    def _pick_next_project(self) -> Optional[Project]:
        """挑选下一个待处理项目（按创建时间）"""
        with self._lock:
            candidates = [p for p in self.projects.values()
                          if p.status in (Status.PENDING, Status.RETRYING)]
            if not candidates:
                return None
            candidates.sort(key=lambda p: p.created_at)
            return candidates[0]

    def _run_project(self, proj: Project):
        """执行单个项目的完整流水线"""
        try:
            self.logger.info(f"===== 开始执行项目 {proj.project_id} =====")

            # Step 1: 文案转换
            ok = self._step_script_conversion(proj)
            if not ok:
                return

            # Step 2: 音频合成
            ok = self._step_audio_synthesis(proj)
            if not ok:
                return

            # Step 3: 视频合成
            ok = self._step_video_stitch(proj)
            if not ok:
                return

            # Step 4: B站上传（可选）
            if self.pipeline_cfg.get("enable_bili_upload"):
                ok = self._step_bili_upload(proj)
                if not ok:
                    return

            self._update_status(proj, Status.COMPLETED, "全部流程已完成")
            self.logger.success(f"项目 {proj.project_id} 全部完成！输出: {proj.output_video}")

            # 移动源文件到 done
            done_path = os.path.join(self.queue_done, os.path.basename(proj.source_file))
            if os.path.exists(proj.source_file) and not os.path.exists(done_path):
                shutil.move(proj.source_file, done_path)
                self._done_files.add(os.path.basename(proj.source_file))

        except Exception as e:
            self._handle_failure(proj, f"项目执行异常: {e}")
            traceback.print_exc()

    # ---------- Step 1: 文案转换 ----------

    def _step_script_conversion(self, proj: Project) -> bool:
        self._update_status(proj, Status.SCRIPT_CONVERTING, "正在生成标准配音脚本")

        proj_dir = os.path.join(self.projects_dir, proj.project_id)
        os.makedirs(proj_dir, exist_ok=True)

        source = proj.source_file
        ext = os.path.splitext(source)[1].lower()
        script_path = os.path.join(proj_dir, "script.txt")

        try:
            if ext == ".txt":
                # 直接读取文案文件，转换格式
                with open(source, "r", encoding="utf-8") as f:
                    raw = f.read()
                standard_script = self._convert_to_standard_script(raw)
            else:
                # 图片：这里先做占位，实际应调用OCR+AI处理
                self.logger.warn(f"[{proj.project_id}] 图片源暂不支持自动OCR，需要预先转成txt")
                fallback = self.available_chars[0] if self.available_chars else "A"
                fallback2 = self.available_chars[1] if len(self.available_chars) > 1 else fallback
                standard_script = f"[{fallback}] 这是一段示例文案，请替换为实际内容。\n[{fallback2}] 收到，请提供图片的实际文字。\n"

            with open(script_path, "w", encoding="utf-8") as f:
                f.write(standard_script)

            proj.script_path = script_path
            self._update_status(proj, Status.SCRIPT_READY, f"脚本已生成: {script_path}")
            return True

        except Exception as e:
            self._handle_failure(proj, f"文案转换失败: {e}")
            return False

    def _convert_to_standard_script(self, raw_text: str) -> str:
        """
        将各种输入格式转换为音频端标准脚本格式 [角色标识] xxx \n [角色标识] xxx
        支持：
        1. 我们之前的分段格式：1（第1段）\n----\n台词
        2. 纯对话格式（角色名: 台词）
        3. 已经是标准格式（直接返回）

        角色标识使用音频端实际可用的 char_id（如 玉玉、柊優花），
        按出现顺序从 self.available_chars 中分配。
        """
        lines = raw_text.strip().split("\n")
        result_lines = []
        available = list(self.available_chars)  # 复制一份，避免修改原列表

        def _assign_alias(raw_name: str, char_map: dict) -> str:
            """按出现顺序从可用角色中分配标识"""
            if raw_name not in char_map:
                idx = len(char_map)
                if idx < len(available):
                    char_map[raw_name] = available[idx]
                else:
                    # 角色不够用，循环复用最后一个
                    char_map[raw_name] = available[-1] if available else "A"
            return char_map[raw_name]

        # 检测是否已经是标准格式（且使用的角色标识在可用列表中）
        def _is_valid_standard_format():
            for line in lines[:10]:
                line = line.strip()
                if not line:
                    continue
                m = re.match(r'^\[([^\]]+?)\]\s*(.+)$', line)
                if m:
                    char_id = m.group(1).strip()
                    # 检查是否包含语言标注，如 [A-中文]
                    if "-" in char_id:
                        char_id = char_id.rsplit("-", 1)[0].strip()
                    if char_id not in available:
                        return False
                elif line:
                    return False
            return True

        if _is_valid_standard_format():
            return raw_text.strip()

        # 检测是否是我们之前的分段格式：N（第M段）\n----\n台词
        i = 0
        char_map = {}  # 原始角色号 -> 实际char_id 映射

        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # 匹配 "1（第1段）" 或 "1(第1段)"
            m = re.match(r'^(\d+)\s*[（(]第(\d+)段[）)]\s*$', line)
            if m:
                char_num = m.group(1)
                # 跳过 ----
                i += 1
                if i < len(lines) and lines[i].strip().startswith("-"):
                    i += 1
                # 收集台词直到下一个分段头或文件结束
                dialog_lines = []
                while i < len(lines):
                    next_line = lines[i].strip()
                    if re.match(r'^\d+\s*[（(]第\d+段[）)]\s*$', next_line):
                        break
                    if next_line:
                        dialog_lines.append(next_line)
                    i += 1

                alias = _assign_alias(char_num, char_map)

                # 合并连续发言
                text = " ".join(dialog_lines).strip()
                if text:
                    result_lines.append(f"[{alias}] {text}")
                continue

            # 检测 "角色名: 台词" 格式
            m2 = re.match(r'^([^:]+?)[:：]\s*(.+)$', line)
            if m2:
                raw_name = m2.group(1).strip()
                text = m2.group(2).strip()
                alias = _assign_alias(raw_name, char_map)
                result_lines.append(f"[{alias}] {text}")
                i += 1
                continue

            # 其他行，尝试作为纯文案保留
            if line and not line.startswith("-"):
                alias = _assign_alias("__default__", char_map)
                result_lines.append(f"[{alias}] {line}")
            i += 1

        if result_lines:
            return "\n".join(result_lines)

        # 兜底：全部给第一个可用角色
        fallback = available[0] if available else "A"
        return f"[{fallback}] " + raw_text.strip().replace("\n", f"\n[{fallback}] ")

    # ---------- Step 2: 音频合成 ----------

    def _step_audio_synthesis(self, proj: Project) -> bool:
        self._update_status(proj, Status.AUDIO_SYNTHESIZING, "正在调用 GPT-SoVITS 配音")

        audio_params = self.cfg.get("audio_params", {})
        python_exe = self.paths.get("python_runtime", sys.executable)
        pipeline_script = os.path.join(self.audio_base, "audio_synthesis_pipeline.py")

        cmd = [
            python_exe, pipeline_script,
            "--project", proj.project_id,
            "--script", proj.script_path,
            "--output_dir", os.path.join(self.audio_base, "project_output"),
            "--top_k", str(audio_params.get("top_k", 20)),
            "--top_p", str(audio_params.get("top_p", 0.6)),
            "--temperature", str(audio_params.get("temperature", 0.6)),
            "--speed", str(audio_params.get("speed", 1.0)),
            "--pause", str(audio_params.get("pause", 0.3)),
        ]

        self.logger.info(f"[{proj.project_id}] 音频命令: {' '.join(cmd[:6])} ...")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3600,  # 最长1小时
            )

            if proc.returncode != 0:
                err = proc.stderr[-500:] if proc.stderr else "未知错误"
                self._handle_failure(proj, f"音频合成失败 (code={proc.returncode}): {err}")
                return False

            proj.audio_output_dir = os.path.join(self.audio_base, "project_output", proj.project_id)
            self._update_status(proj, Status.AUDIO_DONE, f"音频已输出: {proj.audio_output_dir}")
            return True

        except subprocess.TimeoutExpired:
            self._handle_failure(proj, "音频合成超时（超过1小时）")
            return False
        except Exception as e:
            self._handle_failure(proj, f"音频合成异常: {e}")
            return False

    # ---------- Step 3: 视频合成 ----------

    def _step_video_stitch(self, proj: Project) -> bool:
        self._update_status(proj, Status.VIDEO_SYNTHESIZING, "正在调用 Video Stitcher 合成视频")

        source_dir = proj.audio_output_dir
        if not source_dir or not os.path.exists(source_dir):
            self._handle_failure(proj, f"音频输出目录不存在: {source_dir}")
            return False

        main_script = os.path.join(self.video_base, "src", "main.py")
        output_path = os.path.join(self.final_output, f"{proj.project_id}.mp4")

        cmd = [
            sys.executable, main_script,
            "--project", proj.project_id,
            "--source-dir", source_dir,
            "--output", output_path,
        ]

        # 如果配置了字幕
        sub_cfg = self.cfg.get("video_params", {}).get("subtitle_config")
        if sub_cfg:
            full_sub = os.path.join(self.video_base, sub_cfg)
            if os.path.exists(full_sub):
                cmd.extend(["--subtitle-config", full_sub])

        self.logger.info(f"[{proj.project_id}] 视频命令: {' '.join(cmd[:8])} ...")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,  # 最长30分钟
            )

            if proc.returncode != 0:
                err = proc.stderr[-500:] if proc.stderr else "未知错误"
                self._handle_failure(proj, f"视频合成失败 (code={proc.returncode}): {err}")
                return False

            # 确认输出文件存在
            if not os.path.exists(output_path):
                # 视频端可能输出到默认目录，查找一下
                alt = os.path.join(self.video_base, "output", f"{proj.project_id}.mp4")
                if os.path.exists(alt):
                    shutil.move(alt, output_path)

            if os.path.exists(output_path):
                proj.output_video = output_path
                self._update_status(proj, Status.VIDEO_DONE, f"视频已输出: {output_path}")
                return True
            else:
                self._handle_failure(proj, "视频合成后找不到输出文件")
                return False

        except subprocess.TimeoutExpired:
            self._handle_failure(proj, "视频合成超时（超过30分钟）")
            return False
        except Exception as e:
            self._handle_failure(proj, f"视频合成异常: {e}")
            return False

    # ---------- Step 4: B站上传（可选） ----------

    def _step_bili_upload(self, proj: Project) -> bool:
        self._update_status(proj, Status.BILI_UPLOADING, "正在调用 B站上传脚本")

        bili_base = self.paths.get("bili_uploader_base")
        if not bili_base or not os.path.exists(bili_base):
            self.logger.warn(f"[{proj.project_id}] B站上传目录不存在，跳过")
            return True  # 不致命，算成功

        # TODO: 根据你的 BiliAutoUpload 脚本接口调用
        # 这里先占位
        self.logger.info(f"[{proj.project_id}] B站上传步骤待实现（占位）")
        self._update_status(proj, Status.COMPLETED, "B站上传完成（占位）")
        return True

    # ---------- 失败处理 ----------

    def _handle_failure(self, proj: Project, error: str):
        proj.retry_count += 1
        max_retries = self.pipeline_cfg.get("max_retries", 2)

        if proj.retry_count <= max_retries:
            self._update_status(proj, Status.RETRYING, f"第{proj.retry_count}次重试...", error)
            self.logger.warn(f"[{proj.project_id}] {error} | 将在 {self.pipeline_cfg.get('retry_delay_sec', 10)} 秒后重试")
            time.sleep(self.pipeline_cfg.get("retry_delay_sec", 10))
        else:
            self._update_status(proj, Status.FAILED, "已达最大重试次数", error)
            self.logger.error(f"[{proj.project_id}] 项目失败: {error}")

    # ---------- 状态查询 ----------

    def get_all_projects(self) -> List[Project]:
        with self._lock:
            return list(self.projects.values())

    def get_project(self, pid: str) -> Optional[Project]:
        with self._lock:
            return self.projects.get(pid)

    def retry_project(self, pid: str) -> bool:
        proj = self.get_project(pid)
        if not proj:
            return False
        if proj.status == Status.FAILED:
            proj.retry_count = 0
            proj.error_msg = ""
            self._update_status(proj, Status.PENDING, "手动触发重试")
            return True
        return False

    def skip_project(self, pid: str) -> bool:
        proj = self.get_project(pid)
        if not proj:
            return False
        self._update_status(proj, Status.COMPLETED, "已手动跳过")
        return True


# ==================== 命令行入口 ====================

def main():
    config = load_config()
    logger = PipelineLogger(config["paths"]["logs_dir"])
    orch = PipelineOrchestrator(config, logger)

    print("=" * 50)
    print(f"  {config['app_name']} v{config['version']}")
    print("=" * 50)
    print("\n可用命令:")
    print("  start  - 启动调度器")
    print("  status - 查看项目状态")
    print("  exit   - 退出\n")

    orch.start()

    while True:
        try:
            cmd = input("> ").strip().lower()
            if cmd == "start":
                orch.start()
            elif cmd == "status":
                for p in orch.get_all_projects():
                    print(f"  {p.project_id}: {p.status.value} | {p.step}")
            elif cmd == "exit":
                orch.stop()
                break
            else:
                time.sleep(1)
        except (KeyboardInterrupt, EOFError):
            orch.stop()
            break


if __name__ == "__main__":
    main()
