#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""流水线调度器快速测试脚本"""

import os
from pipeline_orchestrator import PipelineOrchestrator, PipelineLogger, load_config

config = load_config()
logger = PipelineLogger(config["paths"]["logs_dir"])
orch = PipelineOrchestrator(config, logger)

# 清理测试环境
for d in ["queue/pending", "queue/done"]:
    if os.path.exists(d):
        for f in os.listdir(d):
            try:
                os.remove(os.path.join(d, f))
            except Exception:
                pass

# 写一个测试文案
test_file = "queue/pending/test_蜜雪冰城.txt"
with open(test_file, "w", encoding="utf-8") as f:
    f.write("""1（第1段）
----
本人有幸喝过一次蜜雪冰城。当时一对情侣吵架女生把手里的摔了，我正好路过溅到我嘴里一滴，至今回味无穷。

2（第2段）
----
能简单描述一下吗？比如入口时的口感？

1（第3段）
----
是冰碴子撞碎在味蕾上的脆响，是甜腻裹着酸涩的余韵。
""")

# 扫描并创建项目
files = orch.scan_queue()
print(f"扫描到 {len(files)} 个待处理文件")
for filepath in files:
    proj = orch.create_project(filepath)
    print(f"创建项目: {proj.project_id}")

    # 手动执行第一步：文案转换
    ok = orch._step_script_conversion(proj)
    print(f"  文案转换: {'成功' if ok else '失败'}")
    if ok and os.path.exists(proj.script_path):
        with open(proj.script_path, "r", encoding="utf-8") as f2:
            content = f2.read().strip()
        print("  脚本内容:")
        for line in content.split("\n")[:5]:
            print(f"    {line}")

print()
print("=" * 40)
print("测试完成！")
print("下一步：把音频端的角色资产准备好后，可以启动GUI测试完整链路。")
