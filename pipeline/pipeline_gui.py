#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AIBLI 流水线 GUI 监控面板

功能：
- 实时显示项目队列与执行状态
- 滚动日志输出
- 控制按钮：开始/暂停、重试、跳过、打开输出目录
- 统计信息：今日处理数、成功率等

双击运行或命令行: python pipeline_gui.py
"""

import os
import sys
import subprocess
import threading
import webbrowser
from datetime import datetime
from tkinter import (
    Tk, Frame, Label, Button, Scrollbar, Text,
    messagebox, filedialog, StringVar, ttk
)
from tkinter.ttk import Treeview

# 把当前目录加入路径，确保能 import pipeline_orchestrator
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline_orchestrator import (
    PipelineOrchestrator, PipelineLogger, Status,
    load_config
)


# ==================== 颜色主题 ====================

COLORS = {
    Status.PENDING:           ("#888888", "等待中"),
    Status.SCRIPT_CONVERTING: ("#2196F3", "文案转换"),
    Status.SCRIPT_READY:      ("#03A9F4", "文案就绪"),
    Status.AUDIO_SYNTHESIZING:("#9C27B0", "音频合成"),
    Status.AUDIO_DONE:        ("#673AB7", "音频完成"),
    Status.VIDEO_SYNTHESIZING:("#FF9800", "视频合成"),
    Status.VIDEO_DONE:        ("#FF5722", "视频完成"),
    Status.BILI_UPLOADING:    ("#795548", "B站上传"),
    Status.COMPLETED:         ("#4CAF50", "已完成"),
    Status.FAILED:            ("#F44336", "失败"),
    Status.RETRYING:          ("#FFEB3B", "重试中"),
}

BG_DARK = "#1e1e1e"
BG_PANEL = "#252526"
FG_TEXT = "#d4d4d4"
ACCENT = "#007acc"
FONT_FAMILY = ("Microsoft YaHei UI", 10)
FONT_FAMILY_SMALL = ("Microsoft YaHei UI", 9)
FONT_MONO = ("Consolas", 10)


# ==================== GUI 类 ====================

class PipelineGUI:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("AIBLI 自动化流水线调度器")
        self.root.geometry("1200x750")
        self.root.configure(bg=BG_DARK)
        self.root.minsize(900, 600)

        # 配置 & 核心
        self.config = load_config()
        self.logger = PipelineLogger(self.config["paths"]["logs_dir"])
        self.orchestrator = PipelineOrchestrator(self.config, self.logger)

        # 绑定日志监听器
        self.logger.add_listener(self._on_log)
        self.orchestrator.add_callback(self._on_project_update)

        self._build_ui()
        self._start_refresh_loop()

        # 如果配置里设置了 auto_start，自动启动
        if self.config.get("pipeline", {}).get("auto_start", False):
            self._toggle_run()

    # ---------- UI 构建 ----------

    def _build_ui(self):
        # 顶部标题栏
        self._build_header()

        # 主体：左右分栏
        main_frame = Frame(self.root, bg=BG_DARK)
        main_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        main_frame.columnconfigure(0, weight=4)
        main_frame.columnconfigure(1, weight=6)
        main_frame.rowconfigure(0, weight=1)

        # 左侧面板：项目列表 + 统计
        left_frame = Frame(main_frame, bg=BG_PANEL, bd=1, relief="solid")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=3)
        left_frame.rowconfigure(1, weight=1)

        self._build_project_list(left_frame)
        self._build_stats_panel(left_frame)

        # 右侧面板：日志
        right_frame = Frame(main_frame, bg=BG_PANEL, bd=1, relief="solid")
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(1, weight=1)

        self._build_log_panel(right_frame)

        # 底部控制栏
        self._build_control_bar()

    def _build_header(self):
        header = Frame(self.root, bg=BG_DARK, height=50)
        header.pack(fill="x", padx=10, pady=10)
        header.pack_propagate(False)

        Label(
            header, text="AIBLI 自动化流水线",
            bg=BG_DARK, fg="#ffffff", font=("Microsoft YaHei UI", 16, "bold")
        ).pack(side="left")

        self.status_var = StringVar(value="状态: 已停止")
        Label(
            header, textvariable=self.status_var,
            bg=BG_DARK, fg=FG_TEXT, font=FONT_FAMILY
        ).pack(side="right", padx=10)

        self.indicator = Label(header, text="●", bg=BG_DARK, fg="#F44336", font=("", 14))
        self.indicator.pack(side="right")

    def _build_project_list(self, parent):
        # 标题
        title = Frame(parent, bg=BG_PANEL)
        title.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        Label(title, text="项目队列", bg=BG_PANEL, fg="#ffffff", font=("Microsoft YaHei UI", 11, "bold")).pack(side="left")

        # 工具栏
        toolbar = Frame(parent, bg=BG_PANEL)
        toolbar.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 0))
        Button(toolbar, text="+ 添加文案", command=self._add_script_file,
               bg=ACCENT, fg="white", font=FONT_FAMILY_SMALL, relief="flat", cursor="hand2").pack(side="left", padx=(0, 5))
        Button(toolbar, text="刷新", command=self._refresh_projects,
               bg="#3c3c3c", fg="white", font=FONT_FAMILY_SMALL, relief="flat", cursor="hand2").pack(side="left")

        # Treeview
        tree_frame = Frame(parent, bg=BG_PANEL)
        tree_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=5)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Custom.Treeview", background="#2d2d30", foreground=FG_TEXT,
                        fieldbackground="#2d2d30", font=FONT_FAMILY_SMALL)
        style.configure("Custom.Treeview.Heading", background="#3c3c3c", foreground="white",
                        font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Custom.Treeview", background=[("selected", "#094771")])

        columns = ("id", "source", "status", "step", "retry", "updated")
        self.tree = Treeview(tree_frame, columns=columns, show="headings",
                                  style="Custom.Treeview", height=12)
        self.tree.heading("id", text="项目ID")
        self.tree.heading("source", text="来源")
        self.tree.heading("status", text="状态")
        self.tree.heading("step", text="当前步骤")
        self.tree.heading("retry", text="重试")
        self.tree.heading("updated", text="更新时间")

        self.tree.column("id", width=70, anchor="center")
        self.tree.column("source", width=120, anchor="w")
        self.tree.column("status", width=80, anchor="center")
        self.tree.column("step", width=120, anchor="w")
        self.tree.column("retry", width=50, anchor="center")
        self.tree.column("updated", width=120, anchor="center")

        vsb = Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # 双击查看详情
        self.tree.bind("<Double-1>", self._on_tree_double_click)

    def _build_stats_panel(self, parent):
        frame = Frame(parent, bg=BG_PANEL, bd=1, relief="solid")
        frame.grid(row=3, column=0, sticky="nsew", padx=8, pady=8)

        Label(frame, text="今日统计", bg=BG_PANEL, fg="#ffffff",
              font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=10, pady=(8, 5))

        stats_grid = Frame(frame, bg=BG_PANEL)
        stats_grid.pack(fill="x", padx=10, pady=5)

        self.stat_total = StringVar(value="0")
        self.stat_done = StringVar(value="0")
        self.stat_failed = StringVar(value="0")
        self.stat_pending = StringVar(value="0")

        stats = [
            ("总项目", self.stat_total, "#03A9F4"),
            ("已完成", self.stat_done, "#4CAF50"),
            ("失败", self.stat_failed, "#F44336"),
            ("等待中", self.stat_pending, "#888888"),
        ]
        for i, (name, var, color) in enumerate(stats):
            cell = Frame(stats_grid, bg=BG_PANEL)
            cell.grid(row=0, column=i, padx=10, pady=5)
            Label(cell, text=name, bg=BG_PANEL, fg="#888888", font=FONT_FAMILY_SMALL).pack()
            Label(cell, textvariable=var, bg=BG_PANEL, fg=color,
                  font=("Microsoft YaHei UI", 18, "bold")).pack()

        # 进度条（当前活跃项目）
        self.progress_var = StringVar(value="当前无活跃项目")
        Label(frame, textvariable=self.progress_var, bg=BG_PANEL, fg=FG_TEXT,
              font=FONT_FAMILY_SMALL).pack(anchor="w", padx=10, pady=(5, 8))

    def _build_log_panel(self, parent):
        Label(parent, text="执行日志", bg=BG_PANEL, fg="#ffffff",
              font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 0))

        # 日志工具栏
        log_toolbar = Frame(parent, bg=BG_PANEL)
        log_toolbar.grid(row=0, column=0, sticky="e", padx=10, pady=(8, 0))
        Button(log_toolbar, text="清空", command=self._clear_logs,
               bg="#3c3c3c", fg="white", font=FONT_FAMILY_SMALL, relief="flat", cursor="hand2").pack(side="right")
        Button(log_toolbar, text="保存日志", command=self._save_logs,
               bg="#3c3c3c", fg="white", font=FONT_FAMILY_SMALL, relief="flat", cursor="hand2").pack(side="right", padx=(0, 5))

        # 日志文本框
        text_frame = Frame(parent, bg=BG_PANEL)
        text_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        self.log_text = Text(text_frame, bg="#1e1e1e", fg=FG_TEXT,
                             font=FONT_MONO, wrap="word",
                             state="disabled", padx=8, pady=5)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_vsb = Scrollbar(text_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_vsb.set)
        log_vsb.grid(row=0, column=1, sticky="ns")

        # 配置标签颜色
        self.log_text.tag_configure("INFO", foreground="#d4d4d4")
        self.log_text.tag_configure("WARN", foreground="#FFEB3B")
        self.log_text.tag_configure("ERROR", foreground="#F44336")
        self.log_text.tag_configure("SUCCESS", foreground="#4CAF50")

    def _build_control_bar(self):
        bar = Frame(self.root, bg=BG_DARK, height=50)
        bar.pack(fill="x", padx=10, pady=(0, 10))
        bar.pack_propagate(False)

        self.run_btn = Button(bar, text="▶ 启动调度", command=self._toggle_run,
                              bg=ACCENT, fg="white", font=FONT_FAMILY,
                              relief="flat", cursor="hand2", width=14)
        self.run_btn.pack(side="left", padx=(0, 10))

        Button(bar, text="🔄 重试选中", command=self._retry_selected,
               bg="#3c3c3c", fg="white", font=FONT_FAMILY,
               relief="flat", cursor="hand2").pack(side="left", padx=5)

        Button(bar, text="⏭ 跳过选中", command=self._skip_selected,
               bg="#3c3c3c", fg="white", font=FONT_FAMILY,
               relief="flat", cursor="hand2").pack(side="left", padx=5)

        Button(bar, text="📂 打开输出", command=self._open_output_dir,
               bg="#3c3c3c", fg="white", font=FONT_FAMILY,
               relief="flat", cursor="hand2").pack(side="left", padx=5)

        Button(bar, text="⚙ 配置", command=self._open_config,
               bg="#3c3c3c", fg="white", font=FONT_FAMILY,
               relief="flat", cursor="hand2").pack(side="left", padx=5)

    # ---------- 交互方法 ----------

    def _toggle_run(self):
        if self.orchestrator._running:
            self.orchestrator.stop()
            self.run_btn.config(text="▶ 启动调度", bg=ACCENT)
            self.indicator.config(fg="#F44336")
            self.status_var.set("状态: 已停止")
        else:
            self.orchestrator.start()
            self.run_btn.config(text="⏹ 停止调度", bg="#F44336")
            self.indicator.config(fg="#4CAF50")
            self.status_var.set("状态: 运行中")

    def _add_script_file(self):
        path = filedialog.askopenfilename(
            title="选择文案文件",
            filetypes=[("文案文件", "*.txt"), ("图片", "*.png;*.jpg;*.jpeg"), ("所有文件", "*.*")]
        )
        if path:
            # 复制到队列
            import shutil
            dest = os.path.join(self.orchestrator.queue_pending, os.path.basename(path))
            shutil.copy2(path, dest)
            self.logger.info(f"手动添加文件到队列: {os.path.basename(path)}")
            self._refresh_projects()

    def _refresh_projects(self):
        self._update_tree()

    def _retry_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选中一个项目")
            return
        pid = self.tree.item(sel[0], "values")[0]
        ok = self.orchestrator.retry_project(pid)
        if ok:
            self.logger.info(f"手动触发项目 {pid} 重试")
        else:
            messagebox.showinfo("提示", f"项目 {pid} 不在可重试状态")

    def _skip_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选中一个项目")
            return
        pid = self.tree.item(sel[0], "values")[0]
        ok = self.orchestrator.skip_project(pid)
        if ok:
            self.logger.info(f"手动跳过项目 {pid}")

    def _open_output_dir(self):
        path = self.config["paths"].get("final_output_dir", "./pipeline/output")
        if os.path.exists(path):
            os.startfile(path)
        else:
            messagebox.showerror("错误", f"输出目录不存在: {path}")

    def _open_config(self):
        path = os.path.join(BASE_DIR, "pipeline_config.json")
        if os.path.exists(path):
            os.startfile(path)

    def _clear_logs(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _save_logs(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt")]
        )
        if path:
            self.log_text.config(state="normal")
            content = self.log_text.get("1.0", "end")
            self.log_text.config(state="disabled")
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self.logger.info(f"日志已保存: {path}")

    # ---------- 回调 & 刷新 ----------

    def _on_log(self, level: str, msg: str):
        """日志监听器回调"""
        self.root.after(0, lambda: self._append_log(level, msg))

    def _append_log(self, level: str, msg: str):
        self.log_text.config(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{level}] {msg}\n"
        self.log_text.insert("end", line, level)

        # 限制行数
        max_lines = self.config.get("logging", {}).get("gui_max_lines", 500)
        all_text = self.log_text.get("1.0", "end")
        if all_text.count("\n") > max_lines + 50:
            # 删除前 100 行
            self.log_text.delete("1.0", "101.0")

        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _on_project_update(self, project):
        """项目状态变更回调"""
        self.root.after(0, self._update_tree)

    def _update_tree(self):
        """刷新项目列表"""
        # 记住选中项
        selected = [self.tree.item(item, "values")[0] for item in self.tree.selection()]

        # 清空
        for item in self.tree.get_children():
            self.tree.delete(item)

        projects = self.orchestrator.get_all_projects()
        # 按创建时间倒序（最新的在上面）
        projects.sort(key=lambda p: p.created_at, reverse=True)

        total = done = failed = pending = 0
        active_proj = None

        for p in projects:
            total += 1
            if p.status == Status.COMPLETED:
                done += 1
            elif p.status == Status.FAILED:
                failed += 1
            elif p.status in (Status.PENDING, Status.RETRYING):
                pending += 1

            if p.status not in (Status.COMPLETED, Status.FAILED, Status.PENDING):
                active_proj = p

            color, _ = COLORS.get(p.status, ("#888888", "未知"))

            source_name = os.path.basename(p.source_file) if p.source_file else "-"
            values = (
                p.project_id,
                source_name[:18] + "..." if len(source_name) > 18 else source_name,
                p.status.value,
                p.step[:20] + "..." if len(p.step) > 20 else p.step,
                str(p.retry_count),
                p.updated_at[11:] if len(p.updated_at) > 10 else p.updated_at,
            )
            item = self.tree.insert("", "end", values=values)
            self.tree.tag_configure(p.project_id, foreground=color)
            self.tree.item(item, tags=(p.project_id,))

            if p.project_id in selected:
                self.tree.selection_add(item)

        # 更新统计
        self.stat_total.set(str(total))
        self.stat_done.set(str(done))
        self.stat_failed.set(str(failed))
        self.stat_pending.set(str(pending))

        # 更新进度提示
        if active_proj:
            self.progress_var.set(f"当前活跃: {active_proj.project_id} — {active_proj.step}")
        else:
            self.progress_var.set("当前无活跃项目")

    def _start_refresh_loop(self):
        """定时刷新项目列表（每2秒）"""
        self._update_tree()
        self.root.after(2000, self._start_refresh_loop)

    def _on_tree_double_click(self, event):
        """双击查看项目详情"""
        sel = self.tree.selection()
        if not sel:
            return
        pid = self.tree.item(sel[0], "values")[0]
        proj = self.orchestrator.get_project(pid)
        if not proj:
            return

        details = f"""项目详情: {pid}
━━━━━━━━━━━━━━━━━━━━
状态: {proj.status.value}
当前步骤: {proj.step}
来源文件: {proj.source_file or '无'}
脚本路径: {proj.script_path or '未生成'}
音频输出: {proj.audio_output_dir or '未完成'}
视频输出: {proj.output_video or '未完成'}
重试次数: {proj.retry_count}
创建时间: {proj.created_at}
更新时间: {proj.updated_at}
错误信息: {proj.error_msg or '无'}
"""
        messagebox.showinfo("项目详情", details)

    # ---------- 生命周期 ----------

    def on_close(self):
        if self.orchestrator._running:
            if messagebox.askyesno("确认", "调度器正在运行，确定要退出吗？"):
                self.orchestrator.stop()
            else:
                return
        self.root.destroy()


# ==================== 入口 ====================

def main():
    root = Tk()
    app = PipelineGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)

    # 日志欢迎语
    app.logger.info("=" * 40)
    app.logger.info(f"  AIBLI 流水线调度器 v{app.config['version']} 已启动")
    app.logger.info("=" * 40)
    app.logger.info("提示：将文案/截图放入 queue/pending/ 文件夹即可自动处理")

    root.mainloop()


if __name__ == "__main__":
    main()
