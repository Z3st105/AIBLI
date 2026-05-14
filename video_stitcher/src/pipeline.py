"""
全自动流水线引擎

功能：
  1. 扫描项目输出目录，发现待处理项目
  2. 读取 project_manifest.json，解析视频合成配置
  3. 自动执行视频合成
  4. 更新项目状态

用法：
  # 扫描所有项目，自动执行 ready_for_video 状态的项目
  python src/pipeline.py --watch-dir "../audio_synthesis/project_output"

  # 只处理指定项目
  python src/pipeline.py --project P001 --watch-dir "../audio_synthesis/project_output"

  # 作为守护进程持续监听（每30秒扫描一次）
  python src/pipeline.py --watch-dir "../audio_synthesis/project_output" --daemon --interval 30
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from main import run_project, _infer_resolution_from_photos
from core.project_scanner import ProjectScanner
from core.log_parser import parse_log_file

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Pipeline")


# ---------------------------------------------------------------------------
# Project Manifest 解析
# ---------------------------------------------------------------------------

def load_manifest(source_dir: Path) -> Optional[Dict[str, Any]]:
    """读取项目文档 project_manifest.json"""
    manifest_path = source_dir / "project_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"解析 project_manifest.json 失败: {e}")
        return None


def save_manifest(source_dir: Path, manifest: Dict[str, Any]):
    """保存项目文档"""
    manifest_path = source_dir / "project_manifest.json"
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存 project_manifest.json 失败: {e}")


def parse_resolution(config_value) -> Optional[tuple]:
    """解析分辨率配置"""
    if config_value == "auto" or config_value is None:
        return None
    if isinstance(config_value, str):
        parts = config_value.replace("x", ",").split(",")
        if len(parts) == 2:
            return (int(parts[0].strip()), int(parts[1].strip()))
    if isinstance(config_value, (list, tuple)) and len(config_value) == 2:
        return (int(config_value[0]), int(config_value[1]))
    return None


# ---------------------------------------------------------------------------
# 项目扫描
# ---------------------------------------------------------------------------

def scan_projects(watch_dir: Path) -> List[Dict[str, Any]]:
    """
    扫描 watch_dir 下的所有项目目录，返回待处理项目列表。
    每个项目包含：project_id, source_dir, manifest, status
    """
    projects = []
    if not watch_dir.exists():
        logger.error(f"监听目录不存在: {watch_dir}")
        return projects

    for item in sorted(watch_dir.iterdir()):
        if not item.is_dir():
            continue
        manifest = load_manifest(item)
        if manifest is None:
            # 兼容旧模式：没有 manifest 但有 timeline.json
            if (item / "timeline.json").exists() or (item / "merged.wav").exists():
                projects.append({
                    "project_id": item.name,
                    "source_dir": item,
                    "manifest": None,
                    "status": "legacy"
                })
            continue

        status = manifest.get("status", "ready_for_video")
        projects.append({
            "project_id": manifest.get("project_id", item.name),
            "source_dir": item,
            "manifest": manifest,
            "status": status
        })

    return projects


def find_next_project(watch_dir: Path) -> Optional[Dict[str, Any]]:
    """查找下一个待处理的项目（status == ready_for_video）"""
    projects = scan_projects(watch_dir)
    for p in projects:
        if p["status"] == "ready_for_video":
            return p
    return None


# ---------------------------------------------------------------------------
# 执行单个项目
# ---------------------------------------------------------------------------

def execute_project(project_info: Dict[str, Any],
                    characters_dir: Optional[Path] = None,
                    output_path: Optional[Path] = None) -> Path:
    """
    根据项目文档执行视频合成。
    自动更新 manifest 状态为 processing -> completed / error。
    """
    source_dir = project_info["source_dir"]
    manifest = project_info["manifest"]

    # 确定 project_id
    if manifest:
        project_id = manifest.get("project_id", source_dir.name)
    else:
        project_id = source_dir.name

    logger.info(f"=== 开始执行项目: {project_id} ===")

    # 更新状态为 processing
    if manifest:
        manifest["status"] = "processing"
        manifest["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save_manifest(source_dir, manifest)

    try:
        # 从 manifest 解析配置
        resolution = None
        fps = 24
        _output_path = output_path  # 外部指定优先
        subtitle_config = None

        if manifest:
            vc = manifest.get("video_config", {})
            resolution = parse_resolution(vc.get("resolution", "auto"))
            fps = vc.get("fps", 24)

            # 字幕配置
            sub_cfg = vc.get("subtitle_config", "default")
            if sub_cfg != "default" and sub_cfg:
                subtitle_config = Path(sub_cfg)

            # 输出路径（仅当外部未指定时从 manifest 读取）
            if _output_path is None:
                out = manifest.get("output", {})
                target_dir = Path(out.get("target_dir", _PROJECT_ROOT / "output"))
                filename = out.get("filename", f"{project_id}.mp4")
                _output_path = target_dir / filename

        if _output_path is None:
            _output_path = _PROJECT_ROOT / "output" / f"{project_id}.mp4"

        # 执行合成
        final_path = run_project(
            project_id=project_id,
            characters_dir=characters_dir,
            output_path=_output_path,
            resolution=resolution,
            fps=fps,
            source_dir=source_dir,
            subtitle_config=subtitle_config
        )

        # 更新状态为 completed
        if manifest:
            manifest["status"] = "completed"
            manifest["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            manifest["output_file"] = str(final_path)
            save_manifest(source_dir, manifest)

        logger.info(f"=== 项目完成: {project_id} ===")
        logger.info(f"输出: {final_path}")
        return final_path

    except Exception as e:
        logger.error(f"项目执行失败: {e}")
        if manifest:
            manifest["status"] = "error"
            manifest["error_message"] = str(e)
            manifest["failed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            save_manifest(source_dir, manifest)
        raise


# ---------------------------------------------------------------------------
# 守护模式
# ---------------------------------------------------------------------------

def run_daemon(watch_dir: Path,
               characters_dir: Optional[Path] = None,
               interval: int = 30):
    """守护模式：持续扫描并执行待处理项目"""
    logger.info(f"守护模式启动，监听目录: {watch_dir}")
    logger.info(f"扫描间隔: {interval}秒")
    logger.info("按 Ctrl+C 停止")

    while True:
        try:
            project = find_next_project(watch_dir)
            if project:
                execute_project(project, characters_dir)
                logger.info("继续扫描下一个项目...")
                continue  # 立即扫描下一个，不等待
            else:
                logger.info(f"暂无待处理项目，{interval}秒后重新扫描...")
        except Exception as e:
            logger.error(f"执行出错: {e}")
            logger.info(f"{interval}秒后重试...")

        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("守护模式已停止")
            break


# ---------------------------------------------------------------------------
# 单次执行
# ---------------------------------------------------------------------------

def run_once(project_id: Optional[str],
             watch_dir: Path,
             characters_dir: Optional[Path] = None):
    """单次执行：处理指定项目或下一个待处理项目"""
    if project_id:
        # 指定项目
        source_dir = watch_dir / project_id
        if not source_dir.exists():
            raise FileNotFoundError(f"项目目录不存在: {source_dir}")
        manifest = load_manifest(source_dir)
        project_info = {
            "project_id": project_id,
            "source_dir": source_dir,
            "manifest": manifest,
            "status": manifest.get("status", "ready_for_video") if manifest else "legacy"
        }
    else:
        # 自动查找下一个
        project_info = find_next_project(watch_dir)
        if project_info is None:
            logger.info("没有待处理的项目（status=ready_for_video）")
            return None

    return execute_project(project_info, characters_dir)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="视频合成全自动流水线")
    parser.add_argument("--watch-dir", "-w", required=True,
                        help="监听目录（音频合成部门输出根目录）")
    parser.add_argument("--project", "-p", default=None,
                        help="指定项目ID（不填则自动查找下一个待处理项目）")
    parser.add_argument("--characters-dir", "-c", default=None,
                        help="角色根目录路径（默认: ./characters）")
    parser.add_argument("--daemon", "-d", action="store_true",
                        help="守护模式：持续监听并自动执行")
    parser.add_argument("--interval", "-i", type=int, default=30,
                        help="守护模式扫描间隔（秒，默认30）")
    parser.add_argument("--list", "-l", action="store_true",
                        help="列出所有项目及其状态，不执行")
    args = parser.parse_args()

    watch_dir = Path(args.watch_dir)
    characters_dir = Path(args.characters_dir) if args.characters_dir else None

    if args.list:
        projects = scan_projects(watch_dir)
        print(f"\n{'项目ID':<30} {'状态':<20} {'来源目录'}")
        print("-" * 80)
        for p in projects:
            pid = p["project_id"]
            status = p["status"]
            src = p["source_dir"]
            print(f"{pid:<30} {status:<20} {src}")
        print()
        return

    if args.daemon:
        run_daemon(watch_dir, characters_dir, args.interval)
    else:
        final = run_once(args.project, watch_dir, characters_dir)
        if final:
            print(f"\n视频已生成: {final}")


if __name__ == "__main__":
    main()
