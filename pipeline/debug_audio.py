#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速调试音频脚本，打印完整输出"""
import subprocess, sys, os

cmd = [
    os.environ.get("GPT_SOVITS_PYTHON", r"D:\AI音库\GPT-SoVITS-v2pro-20250604\runtime\python.exe"),
    os.path.join(os.path.dirname(__file__), "..", "audio_synthesis", "audio_synthesis_pipeline.py"),
    "--project", "P002",
    "--script", os.path.join(os.path.dirname(__file__), "projects", "P002", "script.txt"),
]

print("执行命令:")
print(" ".join(cmd))
print("=" * 50)

proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

with open("audio_debug_output.txt", "w", encoding="utf-8") as f:
    f.write(f"RETURN CODE: {proc.returncode}\n")
    f.write("\n" + "="*50 + "\n[STDOUT]\n" + "="*50 + "\n")
    f.write(proc.stdout)
    f.write("\n" + "="*50 + "\n[STDERR]\n" + "="*50 + "\n")
    f.write(proc.stderr)

print(f"输出已保存到 audio_debug_output.txt (returncode={proc.returncode})")
