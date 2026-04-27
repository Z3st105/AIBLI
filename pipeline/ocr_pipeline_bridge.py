# -*- coding: utf-8 -*-
"""
AIBLI 搞怪截图自动化处理 -> 流水线接入版
============================================
功能：
  1. 扫描 E:\搞怪\待处理\ 中所有图片（排除 已处理 子目录）
  2. 对每张图片进行 OCR 文字识别
  3. 判断属于哪种类型（A/B/C/D）
  4. 按对应规则生成txt文件
     - 原版存到 E:\搞怪\{YYYY-MM-DD}\（保留历史）
     - pipeline 版复制到 D:\AIBLI\pipeline\queue\pending\（供调度器自动消费）
  5. 将处理完的图片移入 E:\搞怪\待处理\已处理\
  6. 输出本次处理的摘要

用法：
  python ocr_pipeline_bridge.py              # 单次运行
  python ocr_pipeline_bridge.py --watch       # 持续监控模式（每30秒扫描一次）
  python ocr_pipeline_bridge.py --dry-run     # 只扫描不处理，预览结果
  python ocr_pipeline_bridge.py --bridge      # 纯桥接模式（跳过OCR，直接把已有的txt复制到queue）

依赖（至少装一个，优先级从高到低）：
  pip install easyocr              # 推荐：效果好，支持中文
  pip install paddleocr            # 效果最好但体积大
  pip install pytesseract          # 需额外安装 Tesseract 程序
  不装任何库也可用 --bridge 模式
"""

import os
import sys
import json
import time
import shutil
import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# ============================================================
# 路径配置
# ============================================================
SOURCE_DIR = Path(r"E:\搞怪\待处理")
PROCESSED_DIR = SOURCE_DIR / "已处理"
OUTPUT_BASE = Path(r"E:\搞怪")
PIPELINE_QUEUE = Path(r"D:\AIBLI\pipeline\queue\pending")
LOG_DIR = Path(r"D:\AIBLI\pipeline\logs")
CONFIG_PATH = Path(r"D:\AIBLI\pipeline\pipeline_config.json")

DEFAULT_CHAR_ORDER = ["玉玉", "柊優花"]


# ============================================================
# OCR 后端（可替换，自动检测可用引擎）
# ============================================================

class OCREngine:
    """OCR 引擎抽象层，按优先级自动选择可用后端"""

    def __init__(self, backend: str = "auto"):
        self.backend = backend
        self._engine = None
        self.backend_name = ""
        self._init_engine()

    def _init_engine(self):
        backends = []
        if self.backend == "auto":
            backends = ["paddleocr", "easyocr", "tesseract"]
        else:
            backends = [self.backend]

        for name in backends:
            try:
                if name == "paddleocr":
                    from paddleocr import PaddleOCR
                    self._engine = PaddleOCR(
                        use_angle_cls=True, lang='ch',
                        show_log=False, use_gpu=False
                    )
                    self.backend_name = "PaddleOCR"
                    print("[OCR] 使用 PaddleOCR 后端")
                    return
                elif name == "easyocr":
                    import easyocr
                    self._engine = easyocr.Reader(['ch_sim', 'en'], gpu=False)
                    self.backend_name = "EasyOCR"
                    print("[OCR] 使用 EasyOCR 后端")
                    return
                elif name == "tesseract":
                    import pytesseract
                    self._engine = pytesseract
                    self.backend_name = "Tesseract"
                    print("[OCR] 使用 Tesseract 后端")
                    return
            except ImportError:
                continue
            except Exception as e:
                print(f"[OCR] {name} 初始化失败: {e}")
                continue

        raise ImportError(
            "未找到可用 OCR 引擎。\n"
            "  安装方法: pip install easyocr\n"
            "          pip install paddleocr paddlepaddle\n"
            "          pip install pytesseract + 安装 Tesseract 程序\n"
            "\n"
            "  或使用 --bridge 模式跳过 OCR，仅桥接已有文件。"
        )

    def recognize(self, image_path: str) -> str:
        if self.backend_name == "PaddleOCR":
            result = self._engine.ocr(image_path, cls=True)
            texts = []
            if result and result[0]:
                for line in result[0]:
                    if len(line) >= 2:
                        texts.append(line[1][0])
            return "\n".join(texts)

        elif self.backend_name == "EasyOCR":
            result = self._engine.readtext(image_path)
            return "\n".join(item[1] for item in result)

        elif self.backend_name == "Tesseract":
            from PIL import Image
            img = Image.open(image_path)
            return self._engine.image_to_string(img, lang='chi_sim+eng')

        return ""


# ============================================================
# 内容分类器
# ============================================================

class ContentTypeClassifier:
    """
    判断 OCR 文字类型：
      A - 多人对话（有分段头 N(第M段) 或对话标记 : / ：/ 说）
      B - 单人独白（第一人称叙述，无角色切换）
      C - 列表/段子（重复句式、编号列表、多条独立短句）
      D - 长文叙事（大段连续文本 >500字）
    """

    @staticmethod
    def classify(text: str) -> Tuple[str, str]:
        text = text.strip()
        if not text:
            return "UNKNOWN", "空内容"

        lines = text.split("\n")
        non_empty = [l.strip() for l in lines if l.strip()]

        if len(non_empty) < 2:
            return "B", "单人独白-短文本"

        # A类：分段格式
        seg_pat = re.compile(r'^\d+\s*[（(]\d+段[）)]\s*$')
        if any(seg_pat.match(l) for l in non_empty[:10]):
            return "A", "多人对话-分段格式"

        # A类：对话标记
        dlg_count = sum(
            1 for l in non_empty[:15]
            if re.match(r'^[^:：]+?[:：]\s*.+$', l)
        )
        if dlg_count >= 2:
            return "A", "多人对话-标记格式"

        # C类：重复句式
        reps = re.findall(r'(?:如果|假如|当)\s*.+?(?:那么|则|就|最后)', text)
        if len(reps) >= 3:
            return "C", "列表/段子-重复句式"

        # C类：编号列表
        num_count = sum(1 for l in non_empty[:10] if re.match(r'^\d+[\.\、\．]\s', l))
        if num_count >= 3 and len(non_empty) > 5:
            return "C", "列表/编号"

        # D类：长文
        total_chars = len(text)
        avg_len = sum(len(l) for l in non_empty) / max(len(non_empty), 1)
        if total_chars > 500 and avg_len > 20:
            return "D", "长文叙事"

        return "B", "单人独白"


# ============================================================
# 主处理器
# ============================================================

class OCRPipelineBridge:
    """截图 OCR -> 分类 -> 双通道输出 -> 流水线队列"""

    def __init__(self, dry_run: bool = False, bridge_only: bool = False):
        self.dry_run = dry_run
        self.bridge_only = bridge_only
        self.ocr = None
        self.classifier = ContentTypeClassifier()

        self.stats = {
            "total_scanned": 0,
            "processed": 0,
            "skipped": 0,
            "skip_reasons": {},
            "by_type": {},
            "errors": [],
        }

        PROCESSED_DIR.mkdir(exist_ok=True)
        PIPELINE_QUEUE.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        # 加载角色顺序
        self.char_order = self._load_char_order()

    def _load_char_order(self) -> List[str]:
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            order = cfg.get("character_mapping", {}).get("default_char_order", [])
            if order:
                return order
        except Exception:
            pass
        return DEFAULT_CHAR_ORDER

    def init_ocr(self):
        if self.ocr is None and not self.bridge_only:
            self.ocr = OCREngine(backend="auto")

    def scan_images(self) -> List[Path]:
        images = []
        exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
        for f in SOURCE_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in exts:
                images.append(f)
        images.sort(key=lambda p: p.stat().st_mtime)
        return images

    def generate_title(self, image_path: Path, text: str) -> str:
        base = image_path.stem
        # 哈希文件名 -> 从内容提取标题
        if len(base) > 20 and re.match(r'^[a-fA-F0-9]+$', base):
            first_line = text.strip().split("\n")[0].strip()[:20]
            title = re.sub(r'[\\/:*?"<>|\r\n]', '', first_line) or f"未命名_{int(time.time())}"
        else:
            title = re.sub(r'[\\/:*?"<>|\r\n]', '', base)
        return title

    def process_image(self, image_path: Path) -> dict:
        result = {
            "file": image_path.name,
            "success": False,
            "title": "",
            "content_type": "",
            "type_desc": "",
            "output_files": [],
            "error": None,
        }

        try:
            # ---- Step 1: OCR ----
            self.init_ocr()
            print(f"\n{'─'*50}")
            print(f"[处理] {image_path.name}")
            print(f"  OCR 识别中...")

            raw_text = self.ocr.recognize(str(image_path))

            if not raw_text or not raw_text.strip():
                result["error"] = "OCR 未识别到文字"
                print(f"  ⚠️ 跳过：未识别到文字")
                return result

            print(f"  识别到 {len(raw_text)} 字符")

            # ---- Step 2: 分类 ----
            content_type, type_desc = self.classifier.classify(raw_text)
            result["content_type"] = content_type
            result["type_desc"] = type_desc
            print(f"  分类：{content_type} ({type_desc})")

            # ---- Step 3: 标题 ----
            title = self.generate_title(image_path, raw_text)
            today = datetime.now().strftime("%Y-%m-%d")
            result["title"] = title

            # ---- Step 4: 写入原版（E:\搞怪\{date}\）----
            date_dir = OUTPUT_BASE / today
            date_dir.mkdir(exist_ok=True)

            original_path = date_dir / f"{title}_{today}.txt"
            counter = 1
            while original_path.exists():
                counter += 1
                original_path = date_dir / f"{title}_{counter}_{today}.txt"

            if not self.dry_run:
                with open(original_path, 'w', encoding='utf-8') as f:
                    f.write(raw_text)
            result["output_files"].append(str(original_path))
            print(f"  原版 -> {original_path.name}")

            # ---- Step 5: 写入 Pipeline Queue ----
            queue_path = PIPELINE_QUEUE / f"{title}.txt"
            counter_q = 1
            while queue_path.exists():
                counter_q += 1
                queue_path = PIPELINE_QUEUE / f"{title}_{counter_q}.txt"

            if not self.dry_run:
                with open(queue_path, 'w', encoding='utf-8') as f:
                    f.write(raw_text)
            result["output_files"].append(str(queue_path))
            print(f"  Pipeline -> queue/pending/{queue_path.name}")

            # ---- Step 6: 移动已处理图片 ----
            if not self.dry_run:
                dest = PROCESSED_DIR / image_path.name
                if dest.exists():
                    stem, suffix = image_path.stem, image_path.suffix
                    dc = 1
                    while dest.exists():
                        dc += 1
                        dest = PROCESSED_DIR / f"{stem}_dup{dc}{suffix}"
                shutil.move(str(image_path), str(dest))
                print(f"  图片 -> 已处理/{dest.name}")

            result["success"] = True
            self.stats["by_type"][f"{content_type}({type_desc})"] = \
                self.stats["by_type"].get(f"{content_type}({type_desc})", 0) + 1

        except Exception as e:
            result["error"] = str(e)
            self.stats["errors"].append(f"{image_path.name}: {e}")
            print(f"  ❌ 错误: {e}")

        return result

    def run_bridge_mode(self) -> dict:
        """
        纯桥接模式：扫描 E:\搞怪\ 下各日期目录的 txt 文件，
        将尚未进入 queue 的文件复制过去。
        用于没有 OCR 库时手动/外部 OCR 后的对接。
        """
        print(f"\n{'='*55}")
        print(f"  AIBLI Pipeline Bridge Mode（纯桥接，跳过OCR）")
        print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*55}")

        # 扫描所有日期目录（格式：YYYY-MM-DD）
        all_txt_files = []
        for subdir in OUTPUT_BASE.iterdir():
            if not subdir.is_dir():
                continue
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', subdir.name):
                continue
            for txt in sorted(subdir.glob("*.txt")):
                all_txt_files.append(txt)

        self.stats["total_scanned"] = len(all_txt_files)
        print(f"\n源根目录: {OUTPUT_BASE}")
        print(f"目标:     {PIPELINE_QUEUE}")
        print(f"发现 {len(all_txt_files)} 个 txt 文件")

        if not all_txt_files:
            print("没有文件需要桥接。")
            return self.stats

        already_in_queue = set(p.name for p in PIPELINE_QUEUE.glob("*.txt"))
        bridged = 0
        skipped_dup = 0

        for txt_path in all_txt_files:
            if txt_path.name in already_in_queue:
                skipped_dup += 1
                continue

            dest = PIPELINE_QUEUE / txt_path.name
            counter = 1
            while dest.exists() or dest.name in already_in_queue:
                stem = txt_path.stem
                counter += 1
                dest = PIPELINE_QUEUE / f"{stem}_bridge_{counter}.txt"

            if not self.dry_run:
                shutil.copy2(txt_path, dest)
            else:
                print(f"  [DRY] 会复制: {txt_path.name}")

            bridged += 1
            rel_parent = txt_path.parent.relative_to(OUTPUT_BASE)
            print(f"  桥接: {rel_parent}/{txt_path.name} -> queue/pending/{dest.name}")

        self.stats["processed"] = bridged
        self.stats["skipped"] = skipped_dup
        if skipped_dup > 0:
            self.stats["skip_reasons"]["已在队列中"] = skipped_dup

        self.print_summary()
        self.write_log()
        return self.stats

    def run_once(self) -> dict:
        """执行一次完整的扫描->处理循环"""
        print(f"\n{'='*55}")
        print(f"  AIBLI OCR Pipeline Bridge")
        print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*55}")

        images = self.scan_images()
        self.stats["total_scanned"] = len(images)

        print(f"\n待处理目录: {SOURCE_DIR}")
        print(f"Pipeline队列: {PIPELINE_QUEUE}")
        print(f"扫描到 {len(images)} 张图片待处理")

        if not images:
            print("没有需要处理的图片。")
            return self.stats

        if self.dry_run:
            print("🔍 [DRY-RUN] 不会写入任何文件或移动图片")

        for img_path in images:
            r = self.process_image(img_path)
            if r["success"]:
                self.stats["processed"] += 1
            else:
                self.stats["skipped"] += 1
                reason = r.get("error", "未知原因")
                self.stats["skip_reasons"][reason] = \
                    self.stats["skip_reasons"].get(reason, 0) + 1

        self.print_summary()
        self.write_log()
        return self.stats

    def print_summary(self):
        print(f"\n{'='*55}")
        print(f"  处理摘要")
        print(f"{'='*55}")
        print(f"  扫描总数:   {self.stats['total_scanned']}")
        print(f"  成功处理:   {self.stats['processed']}")
        print(f"  跳过:       {self.stats['skipped']}")

        if self.stats["skip_reasons"]:
            print(f"\n  跳过原因:")
            for reason, count in self.stats["skip_reasons"].items():
                print(f"    - {reason}: {count}")

        if self.stats["by_type"]:
            print(f"\n  内容分类:")
            for t, count in self.stats["by_type"].items():
                print(f"    - {t}: {count}")

        if self.stats["errors"]:
            print(f"\n  错误:")
            for err in self.stats["errors"]:
                print(f"    ❌ {err}")

        queue_count = len(list(PIPELINE_QUEUE.glob("*.txt")))
        print(f"\nPipeline 队列: {queue_count} 个文件等待调度器处理")

    def write_log(self):
        log_file = LOG_DIR / f"ocr_bridge_{datetime.now().strftime('%Y-%m-%d')}.log"
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{datetime.now().isoformat()}]\n")
            f.write(f"  scanned={self.stats['total_scanned']} "
                     f"processed={self.stats['processed']} "
                     f"skipped={self.stats['skipped']}\n")
            if self.stats["by_type"]:
                f.write(f"  types={json.dumps(self.stats['by_type'], ensure_ascii=False)}\n")
            if self.stats["errors"]:
                f.write(f"  errors={json.dumps(self.stats['errors'], ensure_ascii=False)}\n")

    def run_watch(self, interval: int = 30):
        print(f"\n👁️  监控模式启动 (间隔 {interval}s)")
        print("   按 Ctrl+C 停止\n")
        try:
            while True:
                self.stats = {
                    "total_scanned": 0, "processed": 0, "skipped": 0,
                    "skip_reasons": {}, "by_type": {}, "errors": [],
                }
                self.run_once()
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\n监控已停止。")


def main():
    parser = argparse.ArgumentParser(description="AIBLI OCR -> Pipeline Bridge")
    parser.add_argument("--watch", "-w", action="store_true",
                        help="持续监控模式（每30秒扫描一次）")
    parser.add_argument("--interval", "-i", type=int, default=30,
                        help="监控模式扫描间隔（秒），默认30")
    parser.add_argument("--dry-run", action="store_true",
                        help="只扫描不处理，预览将发生什么")
    parser.add_argument("--bridge", "-b", action="store_true",
                        help="纯桥接模式：跳过OCR，把 E\\搞怪\\{today}\\ 已有的txt复制到queue")
    args = parser.parse_args()

    bridge = OCRPipelineBridge(dry_run=args.dry_run, bridge_only=args.bridge)

    if args.bridge:
        bridge.run_bridge_mode()
    elif args.watch:
        bridge.run_watch(interval=args.interval)
    else:
        bridge.run_once()


if __name__ == "__main__":
    main()
