"""
文件工具函数
"""

from pathlib import Path
from typing import List


def ensure_dir(path: Path) -> Path:
    """确保目录存在，不存在则创建"""
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_files_by_ext(directory: Path, extensions: List[str]) -> List[Path]:
    """
    列出目录下指定扩展名的所有文件（不递归）
    """
    results = []
    for ext in extensions:
        results.extend(directory.glob(f"*{ext}"))
        results.extend(directory.glob(f"*{ext.upper()}"))
    return sorted(set(results))
