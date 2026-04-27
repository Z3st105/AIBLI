"""
视频拼接器 Web 服务
提供前端页面 + REST API，支持直接指定前端输出目录生成视频、下载结果。
一键启动后，浏览器自动打开操作界面。
"""

import logging
import sys
import threading
import uuid
from pathlib import Path
from typing import Dict, Any

from flask import Flask, request, jsonify, send_file, render_template_string

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from main import run_project
from pipeline import scan_projects, find_next_project, execute_project, load_manifest

app = Flask(__name__)

# ---------------------------------------------------------------------------
# 任务状态管理
# ---------------------------------------------------------------------------

tasks: Dict[str, Dict[str, Any]] = {}


class TaskLogHandler(logging.Handler):
    """自定义日志 Handler，将日志捕获到任务状态中。"""

    def __init__(self, task_id: str):
        super().__init__()
        self.task_id = task_id
        self.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s"))

    def emit(self, record):
        msg = self.format(record)
        t = tasks.get(self.task_id)
        if t is not None:
            t["logs"].append(msg)


def _run_generation(task_id: str, project_id: str, source_dir: Path,
                    output_path: Path, resolution, fps: int):
    """在后台线程中运行视频生成。"""
    handler = TaskLogHandler(task_id)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    try:
        tasks[task_id]["status"] = "running"

        final_path = run_project(
            project_id=project_id,
            source_dir=source_dir,
            output_path=output_path,
            resolution=resolution,
            fps=fps
        )

        tasks[task_id]["status"] = "done"
        tasks[task_id]["output_path"] = str(final_path)
        tasks[task_id]["download_url"] = f"/api/download/{final_path.name}"
    except Exception as e:
        tasks[task_id]["status"] = "error"
        tasks[task_id]["logs"].append(f"[ERROR] {e}")
    finally:
        root_logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.json or {}
    project_id = data.get("project_id", "")
    source_dir_str = data.get("source_dir", "")
    source_dir = Path(source_dir_str) if source_dir_str else None
    width = data.get("width")
    height = data.get("height")
    fps = int(data.get("fps", 24))

    if not project_id:
        return jsonify({"error": "请提供项目ID"}), 400

    # 支持直接指定 source_dir 路径，无需先上传
    if source_dir and not source_dir.exists():
        return jsonify({"error": f"音频包路径不存在: {source_dir}"}), 400

    task_id = str(uuid.uuid4())
    output_path = _PROJECT_ROOT / "output" / f"{project_id}.mp4"

    resolution = None
    if width is not None and height is not None:
        resolution = (int(width), int(height))

    tasks[task_id] = {
        "status": "starting",
        "logs": [],
        "output_path": None,
        "download_url": None
    }

    thread = threading.Thread(
        target=_run_generation,
        args=(task_id, project_id, source_dir, output_path, resolution, fps)
    )
    thread.start()

    return jsonify({"task_id": task_id})


@app.route("/api/progress/<task_id>")
def progress(task_id):
    t = tasks.get(task_id)
    if t is None:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify({
        "status": t["status"],
        "logs": t["logs"][-100:],  # 最近 100 条
        "download_url": t.get("download_url")
    })


@app.route("/api/download/<filename>")
def download(filename):
    file_path = _PROJECT_ROOT / "output" / filename
    if not file_path.exists():
        return jsonify({"error": "文件不存在"}), 404
    return send_file(file_path, as_attachment=True)


# ---------------------------------------------------------------------------
# 流水线 API（自动对接音频合成端用）
# ---------------------------------------------------------------------------

@app.route("/api/projects", methods=["GET"])
def list_projects():
    """列出 watch_dir 下所有项目及其状态"""
    watch_dir_str = request.args.get("watch_dir", "")
    if not watch_dir_str:
        return jsonify({"error": "请提供 watch_dir 参数"}), 400
    watch_dir = Path(watch_dir_str)
    if not watch_dir.exists():
        return jsonify({"error": f"目录不存在: {watch_dir}"}), 400

    projects = scan_projects(watch_dir)
    return jsonify({
        "projects": [
            {
                "project_id": p["project_id"],
                "status": p["status"],
                "source_dir": str(p["source_dir"])
            }
            for p in projects
        ]
    })


@app.route("/api/pipeline/run", methods=["POST"])
def pipeline_run():
    """
    流水线模式：自动查找并执行待处理项目。
    前端（音频合成端）完成后调用此接口，自动开始视频合成。
    """
    data = request.json or {}
    watch_dir_str = data.get("watch_dir", "")
    project_id = data.get("project_id", "")

    if not watch_dir_str:
        return jsonify({"error": "请提供 watch_dir"}), 400

    watch_dir = Path(watch_dir_str)
    if not watch_dir.exists():
        return jsonify({"error": f"目录不存在: {watch_dir}"}), 400

    # 查找项目
    if project_id:
        source_dir = watch_dir / project_id
        if not source_dir.exists():
            return jsonify({"error": f"项目不存在: {project_id}"}), 404
        manifest = load_manifest(source_dir)
        project_info = {
            "project_id": project_id,
            "source_dir": source_dir,
            "manifest": manifest,
            "status": manifest.get("status", "ready_for_video") if manifest else "legacy"
        }
    else:
        project_info = find_next_project(watch_dir)
        if project_info is None:
            return jsonify({"message": "没有待处理的项目"}), 200

    # 检查状态
    if project_info["status"] not in ("ready_for_video", "legacy"):
        return jsonify({
            "error": f"项目状态为 '{project_info['status']}'，不可执行"
        }), 400

    # 后台执行
    task_id = str(uuid.uuid4())
    output_path = _PROJECT_ROOT / "output" / f"{project_info['project_id']}.mp4"

    tasks[task_id] = {
        "status": "starting",
        "logs": [],
        "output_path": None,
        "download_url": None
    }

    def _run_pipeline_task(task_id, project_info, output_path):
        handler = TaskLogHandler(task_id)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            tasks[task_id]["status"] = "running"
            final_path = execute_project(project_info, output_path=output_path)
            tasks[task_id]["status"] = "done"
            tasks[task_id]["output_path"] = str(final_path)
            tasks[task_id]["download_url"] = f"/api/download/{final_path.name}"
        except Exception as e:
            tasks[task_id]["status"] = "error"
            tasks[task_id]["logs"].append(f"[ERROR] {e}")
        finally:
            root_logger.removeHandler(handler)

    thread = threading.Thread(
        target=_run_pipeline_task,
        args=(task_id, project_info, output_path)
    )
    thread.start()

    return jsonify({
        "task_id": task_id,
        "project_id": project_info["project_id"],
        "message": f"已开始处理项目: {project_info['project_id']}"
    })


# ---------------------------------------------------------------------------
# 前端页面
# ---------------------------------------------------------------------------

HTML_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Video Stitcher - 本地视频拼接工具</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0f0f0f;
    color: #e0e0e0;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 40px 20px;
  }
  h1 { font-size: 28px; margin-bottom: 8px; color: #fff; }
  .subtitle { color: #888; margin-bottom: 32px; font-size: 14px; }
  .card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 12px;
    padding: 28px;
    width: 100%;
    max-width: 660px;
  }
  .tabs {
    display: flex;
    gap: 0;
    margin-bottom: 24px;
    border-bottom: 1px solid #2a2a2a;
  }
  .tab {
    padding: 10px 20px;
    cursor: pointer;
    color: #666;
    font-size: 14px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
  }
  .tab:hover { color: #aaa; }
  .tab.active { color: #4a9eff; border-bottom-color: #4a9eff; }
  .tab-content { display: none; }
  .tab-content.active { display: block; }
  .form-row {
    display: flex;
    gap: 12px;
    margin-bottom: 16px;
  }
  .form-group { flex: 1; }
  label {
    display: block;
    font-size: 12px;
    color: #888;
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  input[type="text"], input[type="number"], select {
    width: 100%;
    background: #141414;
    border: 1px solid #2a2a2a;
    border-radius: 6px;
    padding: 10px 12px;
    color: #e0e0e0;
    font-size: 14px;
    outline: none;
    transition: border-color 0.2s;
  }
  input[type="text"]:focus, input[type="number"]:focus, select:focus {
    border-color: #4a9eff;
  }
  .btn {
    width: 100%;
    padding: 14px;
    background: #4a9eff;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s;
    margin-top: 8px;
  }
  .btn:hover { background: #3a8eef; }
  .btn:disabled { background: #2a2a2a; color: #666; cursor: not-allowed; }
  .btn-outline {
    background: transparent;
    border: 1px solid #3a3a3a;
    color: #aaa;
    margin-top: 8px;
  }
  .btn-outline:hover { background: #222; color: #e0e0e0; border-color: #555; }
  .project-list {
    background: #141414;
    border: 1px solid #2a2a2a;
    border-radius: 8px;
    margin-bottom: 16px;
    max-height: 200px;
    overflow-y: auto;
  }
  .project-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 14px;
    border-bottom: 1px solid #1a1a1a;
    font-size: 13px;
  }
  .project-item:last-child { border-bottom: none; }
  .project-item:hover { background: #1a1a1a; }
  .project-name { color: #e0e0e0; font-weight: 500; }
  .status-badge {
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
  }
  .status-ready { background: #1a3a1a; color: #4aff4a; }
  .status-completed { background: #1a1a3a; color: #6a6aff; }
  .status-processing { background: #3a3a1a; color: #f0a040; }
  .status-error { background: #3a1a1a; color: #ff4444; }
  .status-legacy { background: #2a2a2a; color: #888; }
  .empty-msg { color: #555; text-align: center; padding: 20px; font-size: 13px; }
  .logs {
    margin-top: 24px;
    background: #0a0a0a;
    border: 1px solid #1a1a1a;
    border-radius: 8px;
    padding: 16px;
    height: 240px;
    overflow-y: auto;
    font-family: "SF Mono", Monaco, monospace;
    font-size: 12px;
    line-height: 1.6;
    color: #aaa;
  }
  .logs .log-line { margin-bottom: 2px; }
  .logs .log-info { color: #4a9eff; }
  .logs .log-warn { color: #f0a040; }
  .logs .log-error { color: #ff4444; }
  .status-bar {
    margin-top: 16px;
    padding: 12px 16px;
    border-radius: 8px;
    font-size: 13px;
    display: none;
  }
  .status-bar.running { background: #1a2a1a; color: #4aff4a; display: block; }
  .status-bar.done { background: #1a2a1a; color: #4aff4a; display: block; }
  .status-bar.error { background: #2a1a1a; color: #ff4444; display: block; }
  .download-link {
    display: inline-block;
    margin-top: 12px;
    padding: 10px 20px;
    background: #2a2a2a;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    color: #4a9eff;
    text-decoration: none;
    font-size: 14px;
    transition: background 0.2s;
  }
  .download-link:hover { background: #333; }
</style>
</head>
<body>

<h1>Video Stitcher</h1>
<p class="subtitle">本地多角色音画同步视频拼接工具</p>

<div class="card">
  <div class="tabs">
    <div class="tab active" data-tab="manual">Manual</div>
    <div class="tab" data-tab="pipeline">Pipeline</div>
  </div>

  <!-- Tab 1: Manual -->
  <div class="tab-content active" id="tab-manual">
    <div class="form-row">
      <div class="form-group" style="flex: 2;">
        <label>Frontend Output Dir</label>
        <input type="text" id="sourceDir" value="D:\\AIBLI\\audio_synthesis\\project_output\\P999_初次合作" placeholder="e.g. D:\\audio_synthesis\\project_output\\P001">
      </div>
      <div class="form-group">
        <label>Project ID</label>
        <input type="text" id="projectId" value="P999_初次合作" placeholder="e.g. P001">
      </div>
    </div>

    <div class="form-row">
      <div class="form-group">
        <label>Resolution</label>
        <select id="preset">
          <option value="auto">Auto (by photo)</option>
          <option value="1080,1920">1080x1920 Vertical</option>
          <option value="1920,1080">1920x1080 Landscape</option>
        </select>
      </div>
      <div class="form-group">
        <label>Width</label>
        <input type="number" id="width" value="" placeholder="auto">
      </div>
      <div class="form-group">
        <label>Height</label>
        <input type="number" id="height" value="" placeholder="auto">
      </div>
      <div class="form-group">
        <label>FPS</label>
        <input type="number" id="fps" value="24">
      </div>
    </div>

    <button class="btn" id="generateBtn">Start Generation</button>
  </div>

  <!-- Tab 2: Pipeline -->
  <div class="tab-content" id="tab-pipeline">
    <div class="form-row">
      <div class="form-group" style="flex: 2;">
        <label>Watch Directory</label>
        <input type="text" id="watchDir" value="D:\\AIBLI\\audio_synthesis\\project_output" placeholder="Audio synthesis output root dir">
      </div>
      <div class="form-group" style="flex: 1;">
        <label>&nbsp;</label>
        <button class="btn btn-outline" id="scanBtn">Scan</button>
      </div>
    </div>

    <div class="project-list" id="projectList">
      <div class="empty-msg">Click "Scan" to discover projects</div>
    </div>

    <div style="display:flex; gap:12px;">
      <button class="btn" id="autoRunBtn" disabled>Run Next Pending</button>
      <button class="btn btn-outline" id="runAllBtn" disabled>Run All Pending</button>
    </div>
  </div>

  <div class="status-bar" id="statusBar"></div>
  <div class="logs" id="logs"></div>
</div>

<script>
  // ---- Tab switching ----
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
    });
  });

  // ---- Shared state ----
  const logs = document.getElementById('logs');
  const statusBar = document.getElementById('statusBar');
  let taskId = null;
  let pollInterval = null;
  let pendingProjects = [];

  function addLog(msg) {
    const div = document.createElement('div');
    div.className = 'log-line log-info';
    div.textContent = msg;
    logs.appendChild(div);
    logs.scrollTop = logs.scrollHeight;
  }

  // ---- Manual mode ----
  const generateBtn = document.getElementById('generateBtn');
  const projectId = document.getElementById('projectId');
  const preset = document.getElementById('preset');
  const widthInput = document.getElementById('width');
  const heightInput = document.getElementById('height');
  const fpsInput = document.getElementById('fps');

  preset.addEventListener('change', () => {
    if (preset.value === 'auto') {
      widthInput.value = '';
      heightInput.value = '';
    } else {
      const [w, h] = preset.value.split(',').map(Number);
      widthInput.value = w;
      heightInput.value = h;
    }
  });

  generateBtn.addEventListener('click', async () => {
    const sourceDir = document.getElementById('sourceDir').value.trim();
    if (!sourceDir) { alert('Please enter source dir'); return; }
    startTask('/api/generate', {
      project_id: projectId.value,
      source_dir: sourceDir,
      fps: parseInt(fpsInput.value),
      ...(widthInput.value && heightInput.value ? { width: parseInt(widthInput.value), height: parseInt(heightInput.value) } : {})
    }, generateBtn);
  });

  // ---- Pipeline mode ----
  const scanBtn = document.getElementById('scanBtn');
  const autoRunBtn = document.getElementById('autoRunBtn');
  const runAllBtn = document.getElementById('runAllBtn');

  scanBtn.addEventListener('click', async () => {
    const watchDir = document.getElementById('watchDir').value.trim();
    if (!watchDir) { alert('Please enter watch dir'); return; }
    scanBtn.disabled = true;
    scanBtn.textContent = 'Scanning...';

    try {
      const res = await fetch('/api/projects?watch_dir=' + encodeURIComponent(watchDir));
      const data = await res.json();
      if (data.error) { alert(data.error); return; }

      const listEl = document.getElementById('projectList');
      pendingProjects = data.projects.filter(p => p.status === 'ready_for_video' || p.status === 'legacy');

      if (!data.projects.length) {
        listEl.innerHTML = '<div class="empty-msg">No projects found</div>';
      } else {
        listEl.innerHTML = data.projects.map(p => {
          const cls = p.status === 'ready_for_video' ? 'status-ready' :
                      p.status === 'completed' ? 'status-completed' :
                      p.status === 'processing' ? 'status-processing' :
                      p.status === 'error' ? 'status-error' : 'status-legacy';
          return `<div class="project-item">
            <span class="project-name">${p.project_id}</span>
            <span class="status-badge ${cls}">${p.status}</span>
          </div>`;
        }).join('');
      }

      autoRunBtn.disabled = pendingProjects.length === 0;
      runAllBtn.disabled = pendingProjects.length === 0;
      addLog('Scan complete: ' + data.projects.length + ' projects, ' + pendingProjects.length + ' pending');
    } finally {
      scanBtn.disabled = false;
      scanBtn.textContent = 'Scan';
    }
  });

  autoRunBtn.addEventListener('click', async () => {
    const watchDir = document.getElementById('watchDir').value.trim();
    startTask('/api/pipeline/run', { watch_dir: watchDir }, autoRunBtn);
  });

  runAllBtn.addEventListener('click', async () => {
    const watchDir = document.getElementById('watchDir').value.trim();
    addLog('Starting batch run for all pending projects...');
    // Run projects one by one
    let remaining = [...pendingProjects];
    async function runNext() {
      if (!remaining.length) {
        addLog('All projects completed!');
        return;
      }
      const p = remaining.shift();
      addLog('Starting: ' + p.project_id);
      await new Promise((resolve) => {
        startTaskSilent('/api/pipeline/run', { watch_dir: watchDir, project_id: p.project_id }, resolve);
      });
      // Small delay then continue
      setTimeout(runNext, 1000);
    }
    runNext();
  });

  // ---- Shared task management ----
  function startTask(url, payload, btn) {
    btn.disabled = true;
    const origText = btn.textContent;
    btn.textContent = 'Running...';
    logs.innerHTML = '';
    statusBar.className = 'status-bar running';
    statusBar.textContent = 'Processing...';
    statusBar.style.display = 'block';

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(res => res.json()).then(data => {
      if (data.error) {
        alert(data.error);
        btn.disabled = false;
        btn.textContent = origText;
        return;
      }
      taskId = data.task_id;
      addLog('Task: ' + taskId + (data.project_id ? ' (' + data.project_id + ')' : ''));
      pollInterval = setInterval(pollProgress, 1500);
    });
  }

  function startTaskSilent(url, payload, callback) {
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(res => res.json()).then(data => {
      if (data.error) {
        addLog('[ERROR] ' + data.error);
        callback();
        return;
      }
      const tid = data.task_id;
      addLog('Task created: ' + tid);

      const interval = setInterval(() => {
        fetch('/api/progress/' + tid).then(r => r.json()).then(d => {
          if (d.status === 'done') {
            clearInterval(interval);
            addLog('[DONE] ' + (data.project_id || '') + ' -> ' + (d.download_url || ''));
            callback();
          } else if (d.status === 'error') {
            clearInterval(interval);
            addLog('[ERROR] Failed: ' + (data.project_id || ''));
            callback();
          }
        });
      }, 2000);
    });
  }

  async function pollProgress() {
    if (!taskId) return;
    const res = await fetch('/api/progress/' + taskId);
    const data = await res.json();
    if (data.error) return;

    logs.innerHTML = '';
    data.logs.forEach(line => {
      const div = document.createElement('div');
      div.className = 'log-line';
      if (line.includes('ERROR')) div.className += ' log-error';
      else if (line.includes('WARN')) div.className += ' log-warn';
      else div.className += ' log-info';
      div.textContent = line;
      logs.appendChild(div);
    });
    logs.scrollTop = logs.scrollHeight;

    if (data.status === 'done') {
      clearInterval(pollInterval);
      statusBar.className = 'status-bar done';
      statusBar.innerHTML = 'Done!<br><a class="download-link" href="' + data.download_url + '">Download</a>';
      generateBtn.disabled = false;
      generateBtn.textContent = 'Start Generation';
      autoRunBtn.disabled = false;
      runAllBtn.disabled = false;
    } else if (data.status === 'error') {
      clearInterval(pollInterval);
      statusBar.className = 'status-bar error';
      statusBar.textContent = 'Failed - check logs';
      generateBtn.disabled = false;
      generateBtn.textContent = 'Start Generation';
      autoRunBtn.disabled = false;
      runAllBtn.disabled = false;
    }
  }
</script>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 50)
    print("Video Stitcher 本地服务")
    print("=" * 50)
    print(f"项目根目录: {_PROJECT_ROOT}")
    print("访问地址: http://127.0.0.1:5000")
    print("按 Ctrl+C 停止服务")
    print("=" * 50)
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
