"""

AI Web Exploration & Testing System — Native Desktop Application

Built with customtkinter

"""

from __future__ import annotations



import asyncio

import base64

import io

import json

import os

import queue

import re

import sys

import threading

import time

import traceback

from datetime import datetime

from pathlib import Path

from tkinter import messagebox



import urllib.request

import urllib.error

import customtkinter as ctk

from PIL import Image



# Ensure the project root is in path

sys.path.insert(0, str(Path(__file__).parent.resolve()))



from config import settings

from models.schemas import (

    ExplorationTask, ExploreStep, TaskResult, TaskStatus,

    StepAction, StepStatus, ElementLocator,

)

from agent.agent import ExplorationAgent

from generators.feature_generator import generate_feature_file

from generators.script_generator import generate_test_script

from generators.page_object_generator import generate_page_object

from executor.test_runner import TestRunner



# ── Theme ───────────────────────────────────────────

ctk.set_appearance_mode("dark")

ctk.set_default_color_theme("blue")

FONT_UI = ("Segoe UI", 13)
FONT_UI_SMALL = ("Segoe UI", 11)
FONT_UI_TINY = ("Segoe UI", 10)
FONT_MONO = ("Cascadia Code", 12)
FONT_HEADING = ("Segoe UI", 16)
FONT_BOLD = ("Segoe UI", 12, "bold")



# ── Constants ───────────────────────────────────────

PAD = 12

FONT_MONO = ("Cascadia Code", "Consolas", "Courier New", "monospace")





# ══════════════════════════════════════════════════════

#  Exploration Worker (background thread)

# ══════════════════════════════════════════════════════



class ExplorationWorker(threading.Thread):

    """Runs the async exploration agent in a background thread.

    Communicates results back via a thread-safe queue."""



    def __init__(self, task: ExplorationTask, ui_queue: queue.Queue):

        super().__init__(daemon=True)

        self.task = task

        self.ui_queue = ui_queue

        self._cancel = threading.Event()



    def cancel(self):

        self._cancel.set()



    def run(self):

        try:

            loop = asyncio.new_event_loop()

            asyncio.set_event_loop(loop)



            agent = ExplorationAgent()



            # Register callbacks

            async def on_step(step: ExploreStep):

                self.ui_queue.put(("step", step))



            async def on_log(message: str):

                self.ui_queue.put(("log", message))



            async def on_snapshot(url, title, screenshot_b64, element_count):

                self.ui_queue.put(("snapshot", {

                    "url": url, "title": title,

                    "screenshot": screenshot_b64, "element_count": element_count,

                }))



            async def on_reasoning(action, description, reasoning):

                self.ui_queue.put(("reasoning", {

                    "action": action, "description": description, "reasoning": reasoning,

                }))



            async def on_status(status, message, step=None, max_步=None):

                self.ui_queue.put(("status", {

                    "status": status, "message": message,

                    "step": step, "max_步": max_步,

                }))



            # Patch callbacks

            original_push = agent._push

            async def patched_push(msg_type, task_id, data):

                if msg_type == "step_update":

                    step_data = data

                    # reconstruct step from dict

                    step = ExploreStep(**step_data) if isinstance(step_data, dict) else step_data

                    await on_step(step)

                elif msg_type == "log":

                    await on_log(data.get("message", ""))

                elif msg_type == "snapshot":

                    await on_snapshot(

                        data.get("url", ""), data.get("title", ""),

                        data.get("screenshot", ""), data.get("element_count", 0),

                    )

                elif msg_type == "reasoning":

                    await on_reasoning(

                        data.get("action", ""), data.get("description", ""), data.get("reasoning", ""),

                    )

                elif msg_type == "status":

                    await on_status(

                        data.get("status", ""), data.get("message", ""),

                        data.get("step"), data.get("max_步"),

                    )

                elif msg_type == "error":

                    self.ui_queue.put(("error", data.get("message", "")))

                await original_push(msg_type, task_id, data)



            agent._push = patched_push



            # Run exploration

            self.ui_queue.put(("status", {"status": "starting", "message": "Starting browser..."}))

            result = loop.run_until_complete(agent.explore(self.task))



            if self._cancel.is_set():

                self.ui_queue.put(("status", {"status": "cancelled", "message": "Cancelled"}))

                return



            result.步 = agent.explorer.步

            self.ui_queue.put(("status", {"status": "generating", "message": "Generating test assets..."}))



            # Generate assets

            feature = generate_feature_file(self.task, result.步)

            po = generate_page_object(result.步, _derive_page_name(self.task.target_url))

            script = generate_test_script(self.task, result.步)



            result.feature_content = feature

            result.page_object_code = po

            result.test_script = script

            result.status = TaskStatus.COMPLETED



            # Save files

            task_dir = settings.OUTPUT_DIR / self.task.id

            task_dir.mkdir(parents=True, exist_ok=True)

            (task_dir / "test.feature").write_text(feature, encoding="utf-8")

            (task_dir / "test_generated.py").write_text(script, encoding="utf-8")

            (task_dir / "page_object.py").write_text(po, encoding="utf-8")



            self.ui_queue.put(("result", result))

            self.ui_queue.put(("status", {"status": "completed", "message": "Done, " + str(int(_time.time()-_start)) + "s — " + str(len(result.步)) + " 步"}))



        except Exception as e:

            self.ui_queue.put(("error", f"{type(e).__name__}: {e}\n{traceback.format_exc()}"))

            self.ui_queue.put(("status", {"status": "failed", "message": str(e)}))





def _derive_page_name(url: str) -> str:

    from urllib.parse import urlparse

    parsed = urlparse(url)

    host = parsed.netloc.replace("www.", "").split(".")[0]

    path = parsed.path.strip("/").replace("/", "_").replace("-", "_")

    if path:

        return f"{host.capitalize()}_{path.capitalize()}Page"

    return f"{host.capitalize()}Page"





# ══════════════════════════════════════════════════════

#  Main Desktop Application

# ══════════════════════════════════════════════════════



class App(ctk.CTk):

    def __init__(self):

        super().__init__()



        self.title("AI Web 探索测试系统")

        # Window icon
        icon_path = Path(__file__).parent / "icon.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(default=str(icon_path))
            except Exception:
                pass
            # Also set taskbar icon via PhotoImage
            try:
                from PIL import Image as PILImage
                img = PILImage.open(icon_path)
                photo = ctk.CTkImage(light_image=img, dark_image=img, size=(32, 32))
                self.iconphoto(False, photo)
            except Exception:
                pass

        self.geometry("1280x820")

        self.minsize(960, 640)



        self._worker: ExplorationWorker | None = None

        self._ui_queue = queue.Queue()

        self._current_task: ExplorationTask | None = None

        self._current_result: TaskResult | None = None

        self._步: list[ExploreStep] = []

        self._step_widgets: list[ctk.CTkFrame] = []

        self._latest_screenshot: str = ""





        # Load saved AI config from .env

        from pathlib import Path as _Path

        _env = _Path(__file__).parent / ".env"

        if _env.exists():

            for _line in _env.read_text(encoding="utf-8").splitlines():

                if _line.startswith("AUTOTEST_AI_API_KEY="):

                    settings.AI_API_KEY = _line.split("=", 1)[1].strip()

                elif _line.startswith("AUTOTEST_AI_API_BASE="):

                    settings.AI_API_BASE = _line.split("=", 1)[1].strip()

                elif _line.startswith("AUTOTEST_AI_MODEL="):

                    settings.AI_MODEL = _line.split("=", 1)[1].strip()



        self._build_ui()

        self._poll_queue()



    # ── Build UI ─────────────────────────────────



    def _build_ui(self):

        self.grid_columnconfigure(1, weight=1)

        self.grid_rowconfigure(0, weight=1)



        self._build_sidebar()

        self._build_main()



    def _build_sidebar(self):
        sidebar = ctk.CTkScrollableFrame(self, width=320, corner_radius=0, fg_color="#1a1d27")
        sidebar.grid(row=0, column=0, sticky="ns")
        P = 10

        ctk.CTkLabel(sidebar, text="AI Web 探索测试", font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold")
                     ).pack(anchor="w", padx=P, pady=(P, 2))
        ctk.CTkLabel(sidebar, text="智能体驱动的自动化测试生成平台", font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                     text_color="white").pack(anchor="w", padx=P, pady=(0, 8))

        self._section_label(sidebar, "目标网址")
        self.entry_url = ctk.CTkEntry(sidebar, placeholder_text="https://example.com", height=32)
        self.entry_url.pack(fill="x", padx=P, pady=(2, 6))

        self._section_label(sidebar, "测试要求")
        self.text_req = ctk.CTkTextbox(sidebar, height=56, font=ctk.CTkFont(size=12))
        self.text_req.pack(fill="x", padx=P, pady=(2, 4))
        self.text_req.insert("1.0", "探索网页所有功能、验证表单提交、检查关键页面元素")

        self._section_label(sidebar, "凭证与配置")
        row = ctk.CTkFrame(sidebar, fg_color="transparent")
        row.pack(fill="x", padx=P, pady=(2, 2))
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=1)
        self.entry_user = ctk.CTkEntry(row, placeholder_text="用户名", height=28, font=ctk.CTkFont(size=11))
        self.entry_user.grid(row=0, column=0, padx=(0, 3), sticky="ew")
        self.entry_pass = ctk.CTkEntry(row, placeholder_text="密码", height=28, font=ctk.CTkFont(size=11), show="*")
        self.entry_pass.grid(row=0, column=1, padx=(3, 0), sticky="ew")

        step_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        step_frame.pack(fill="x", padx=P, pady=(4, 8))
        ctk.CTkLabel(step_frame, text="最大步数", font=ctk.CTkFont(size=11),
                     text_color="white").pack(side="left")
        self.spin_步 = ctk.CTkSegmentedButton(step_frame, values=["20", "50", "100", "200", "500"],
                                                  font=ctk.CTkFont(size=10))
        self.spin_步.set("50")
        self.spin_步.pack(side="right")

        from config import settings
        self.ai_expanded = ctk.BooleanVar(value=True)
        self.ai_header = ctk.CTkButton(
            sidebar, text=" AI 推理设置", font=ctk.CTkFont(size=11),
            fg_color="transparent", hover_color="#2d3148", anchor="w",
            command=self._toggle_ai_settings, height=28)
        self.ai_header.pack(fill="x", padx=P-2, pady=(0, 0))

        self.ai_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        self.ai_frame.pack(fill="x", padx=P, pady=(4, 10))
        self.ai_frame_shown = True

        ctk.CTkLabel(self.ai_frame, text="API Key", font=ctk.CTkFont(size=10),
                     text_color="white").pack(anchor="w", pady=(4, 0))
        self.entry_apikey = ctk.CTkEntry(self.ai_frame, placeholder_text="sk-...", height=28, show="*")
        self.entry_apikey.pack(fill="x", pady=(2, 4))
        if settings.AI_API_KEY:
            self.entry_apikey.insert(0, settings.AI_API_KEY)

        row2 = ctk.CTkFrame(self.ai_frame, fg_color="transparent")
        row2.pack(fill="x")
        row2.grid_columnconfigure(0, weight=1)
        row2.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row2, text="API 地址", font=ctk.CTkFont(size=10), text_color="white"
                     ).grid(row=0, column=0, padx=(0, 3), sticky="w")
        ctk.CTkLabel(row2, text="模型", font=ctk.CTkFont(size=10), text_color="white"
                     ).grid(row=0, column=1, padx=(3, 0), sticky="w")
        self.entry_apibase = ctk.CTkEntry(row2, placeholder_text="https://api.deepseek.com", height=28, font=ctk.CTkFont(size=11))
        self.entry_apibase.grid(row=1, column=0, padx=(0, 3), pady=(2, 0), sticky="ew")
        self.entry_apibase.insert(0, settings.AI_API_BASE)
        self.combo_model = ctk.CTkComboBox(
            row2, values=["deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner", "gpt-4o", "gpt-4o-mini"],
            height=28, font=ctk.CTkFont(size=11))
        self.combo_model.grid(row=1, column=1, padx=(3, 0), pady=(2, 0), sticky="ew")
        self.combo_model.set(settings.AI_MODEL)

        self.lbl_ai_status = ctk.CTkLabel(self.ai_frame, text="", font=ctk.CTkFont(size=10), text_color="#22c55e")
        self.lbl_ai_status.pack(anchor="w", pady=(4, 0))
        self._update_ai_status_label()

        btn_ai = ctk.CTkFrame(self.ai_frame, fg_color="transparent")
        btn_ai.pack(fill="x", pady=(4, 6))
        btn_ai.grid_columnconfigure(0, weight=1)
        btn_ai.grid_columnconfigure(1, weight=1)
        self.btn_save_ai = ctk.CTkButton(btn_ai, text="保存", command=self._on_save_ai_config,
                                          height=26, fg_color="#374151", hover_color="#4b5563", text_color="white", font=ctk.CTkFont(size=11))
        self.btn_save_ai.grid(row=0, column=0, padx=(0, 3), sticky="ew")
        self.btn_test_ai = ctk.CTkButton(btn_ai, text="测试连接", command=self._on_test_ai_connection,
                                          height=26, fg_color="#1e40af", hover_color="#1d4ed8", text_color="white", font=ctk.CTkFont(size=11))
        self.btn_test_ai.grid(row=0, column=1, padx=(3, 0), sticky="ew")

        btn_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        btn_frame.pack(fill="x", padx=P, pady=(10, 4))
        btn_frame.grid_columnconfigure(0, weight=1)
        btn_frame.grid_columnconfigure(1, weight=1)
        self.btn_start = ctk.CTkButton(btn_frame, text="开始探索", command=self._on_start,
                                        height=36, fg_color="#4f46e5", hover_color="#6366f1", text_color="white", font=ctk.CTkFont(size=13, weight="bold"))
        self.btn_start.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.btn_stop = ctk.CTkButton(btn_frame, text="停止", command=self._on_stop,
                                       height=36, fg_color="gray30", hover_color="gray40", text_color="white", font=ctk.CTkFont(size=13, weight="bold"),
                                       state="disabled")
        self.btn_stop.grid(row=0, column=1, padx=(4, 0), sticky="ew")

        self.lbl_status = ctk.CTkLabel(sidebar, text="就绪", font=ctk.CTkFont(size=10),
                                       text_color="white")
        self.lbl_status.pack(anchor="w", padx=P, pady=(2, 0))
        self.progress = ctk.CTkProgressBar(sidebar, height=5)
        self.progress.pack(fill="x", padx=P, pady=(2, 4))
        self.progress.set(0)
        self.btn_run = ctk.CTkButton(sidebar, text="运行生成的测试", command=self._on_run_tests,
                                      height=32, fg_color="#16a34a", hover_color="#22c55e", text_color="white",
                                      state="disabled", font=ctk.CTkFont(size=13, weight="bold"))
        self.btn_run.pack(fill="x", padx=P, pady=(2, 10))

    def _section_label(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                     text_color="white").pack(anchor="w", padx=10)

    def _on_save_ai_config(self):
        api_key = self.entry_apikey.get().strip()
        api_base = self.entry_apibase.get().strip()
        model = self.combo_model.get()
        from config import settings as _s
        if api_key:
            _s.AI_API_KEY = api_key
        if api_base:
            _s.AI_API_BASE = api_base
        if model:
            _s.AI_MODEL = model
        self._save_ai_config(api_key, api_base, model)
        self._update_ai_status_label()
        from tkinter import messagebox
        messagebox.showinfo("Saved", "AI config saved")

    def _on_test_ai_connection(self):
        api_key = self.entry_apikey.get().strip()
        api_base = self.entry_apibase.get().strip()
        if not api_key:
            from tkinter import messagebox
            messagebox.showwarning("Missing Key", "Please enter API Key first")
            return
        if not api_base:
            api_base = "https://api.deepseek.com"
        self.btn_test_ai.configure(text="Testing...", state="disabled")
        self.update()
        import threading, json, urllib.request, urllib.error
        def do_test():
            try:
                data = json.dumps({"model": self.combo_model.get(), "messages": [{"role":"user","content":"hi"}], "max_tokens":5}).encode()
                req = urllib.request.Request(api_base.rstrip("/") + "/chat/completions", data=data,
                    headers={"Authorization":"Bearer "+api_key,"Content-Type":"application/json"})
                resp = urllib.request.urlopen(req, timeout=15)
                result = json.loads(resp.read())
                if "choices" in result:
                    self._ui_queue.put(("ai_test", ("ok", result["model"])))
                else:
                    self._ui_queue.put(("ai_test", ("fail", str(result)[:200])))
            except urllib.error.HTTPError as e:
                msg = json.loads(e.read()) if e.fp else {}
                self._ui_queue.put(("ai_test", ("fail", "HTTP "+str(e.code)+": "+str(msg.get("error",{}).get("message",str(e))))))
            except Exception as e:
                self._ui_queue.put(("ai_test", ("fail", str(e)[:200])))
        threading.Thread(target=do_test, daemon=True).start()


    def _toggle_ai_settings(self):

        if self.ai_frame_shown:

            self.ai_frame.pack_forget()

        else:

            self.ai_frame.pack(fill="x", padx=10, pady=(4, 10), after=self.ai_header)

        self.ai_frame_shown = not self.ai_frame_shown



    def _update_ai_status_label(self):

        from config import settings

        if settings.AI_API_KEY:

            self.lbl_ai_status.configure(

                text=f" 已配置 ({settings.AI_MODEL})", text_color="#22c55e")

        else:

            self.lbl_ai_status.configure(

                text=" 未配置 — 将使用基础探索策略", text_color="#f59e0b")





    def _save_ai_config(self, api_key, api_base, model=""):

        """Save AI config to .env for persistence"""

        from pathlib import Path

        env_path = Path(__file__).parent / ".env"

        try:

            lines = []

            if env_path.exists():

                lines = env_path.read_text(encoding="utf-8").splitlines()

            new_lines = []

            has_key, has_base = False, False

            for line in lines:

                if line.startswith("AUTOTEST_AI_API_KEY="):

                    new_lines.append("AUTOTEST_AI_API_KEY=" + api_key)

                    has_key = True

                elif line.startswith("AUTOTEST_AI_API_BASE="):

                    new_lines.append("AUTOTEST_AI_API_BASE=" + api_base)

                    has_base = True

                else:

                    new_lines.append(line)

            if not has_key and api_key:

                new_lines.append("AUTOTEST_AI_API_KEY=" + api_key)

            if not has_base and api_base:

                new_lines.append("AUTOTEST_AI_API_BASE=" + api_base)

            has_model = False

            for line in new_lines:

                if line.startswith("AUTOTEST_AI_MODEL="):

                    has_model = True

                    break

            if not has_model and model:

                new_lines.append("AUTOTEST_AI_MODEL=" + model)

            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        except Exception:

            pass



    def _build_main(self):

        main = ctk.CTkFrame(self, corner_radius=0)

        main.grid(row=0, column=1, sticky="nsew")

        main.grid_columnconfigure(0, weight=1)

        main.grid_rowconfigure(0, weight=0)

        main.grid_rowconfigure(1, weight=1)



        # Tabs

        self.tab_view = ctk.CTkTabview(main)

        self.tab_view.grid(row=0, column=0, rowspan=2, padx=PAD, pady=PAD, sticky="nsew")



        self.tab_步 = self.tab_view.add("探索步骤")

        self.tab_screenshot = self.tab_view.add("页面截图")

        self.tab_feature = self.tab_view.add("Feature 文件")

        self.tab_script = self.tab_view.add("测试脚本")

        self.tab_po = self.tab_view.add("Page Object")

        self.tab_log = self.tab_view.add("运行日志")

        self.tab_checklist = self.tab_view.add("功能清单")



        # Steps tab

        self.步_scroll = ctk.CTkScrollableFrame(self.tab_步)

        self.步_scroll.pack(fill="both", expand=True, padx=4, pady=4)

        self.lbl_步_empty = ctk.CTkLabel(self.步_scroll, text="提交任务以开始探索...",

                                            text_color="white", font=ctk.CTkFont(size=14))

        self.lbl_步_empty.pack(expand=True)



        # Screenshot tab

        self.lbl_screenshot = ctk.CTkLabel(self.tab_screenshot, text="暂无截图", text_color="white")

        self.lbl_screenshot.pack(expand=True)



        # Feature tab

        self.text_feature = ctk.CTkTextbox(self.tab_feature, font=ctk.CTkFont(family="Cascadia Code", size=12))

        self.text_feature.pack(fill="both", expand=True, padx=4, pady=4)



        # Script tab

        self.text_script = ctk.CTkTextbox(self.tab_script, font=ctk.CTkFont(family="Cascadia Code", size=12))

        self.text_script.pack(fill="both", expand=True, padx=4, pady=4)



        # Page Object tab

        self.text_po = ctk.CTkTextbox(self.tab_po, font=ctk.CTkFont(family="Cascadia Code", size=12))

        self.text_po.pack(fill="both", expand=True, padx=4, pady=4)



        # Log tab

        self.text_log = ctk.CTkTextbox(self.tab_log, font=ctk.CTkFont(family="Cascadia Code", size=12))

        self.text_log.pack(fill="both", expand=True, padx=4, pady=4)



        self.text_checklist = ctk.CTkTextbox(self.tab_checklist, font=ctk.CTkFont(size=13))

        self.text_checklist.pack(fill="both", expand=True, padx=4, pady=4)



    # ── Actions ──────────────────────────────────



    def _on_start(self):

        url = self.entry_url.get().strip()

        if not url:

            messagebox.showwarning("缺少网址", "请输入目标网址。")

            return

        if not url.startswith("http"):

            url = "https://" + url

            self.entry_url.delete(0, "end")

            self.entry_url.insert(0, url)



        reqs = self.text_req.get("1.0", "end-1c").strip()

        username = self.entry_user.get().strip() or None

        password = self.entry_pass.get().strip() or None

        api_key = self.entry_apikey.get().strip()

        api_base = self.entry_apibase.get().strip()

        model = self.combo_model.get()

        if api_key:

            from config import settings as _s

            _s.AI_API_KEY = api_key

            _s.AI_MODEL = self.combo_model.get()

            self._update_ai_status_label()

            if api_base:

                _s.AI_API_BASE = api_base

            # Save to .env for persistence

            self._save_ai_config(api_key, api_base)



        max_步 = int(self.spin_步.get())



        task = ExplorationTask(

            target_url=url, requirements=reqs,

            username=username, password=password,

            max_步=max_步,

        )

        self._current_task = task

        self._current_result = None

        self._步.clear()

        self._step_widgets.clear()

        self._步_summary = None

        self._latest_screenshot = ""



        # Clear UI

        for w in self.步_scroll.winfo_children():

            w.destroy()

        self.lbl_步_empty = ctk.CTkLabel(self.步_scroll, text="正在启动探索...",

                                            text_color="white", font=ctk.CTkFont(size=14))

        self.lbl_步_empty.pack(expand=True)



        self.text_feature.delete("1.0", "end")

        self.text_script.delete("1.0", "end")

        self.text_po.delete("1.0", "end")

        self.text_log.delete("1.0", "end")

        self.lbl_screenshot.configure(image="", text="等待中...")

        self.progress.set(0)



        # Disable start, enable stop

        self.btn_start.configure(state="disabled", text="探索中...")

        self.btn_stop.configure(state="normal", text="停止")

        self.btn_run.configure(state="disabled")

        self.lbl_status.configure(text="正在启动浏览器...", text_color="#818cf8")



        # Start worker

        self._worker = ExplorationWorker(task, self._ui_queue)

        self._worker.start()



    def _on_stop(self):

        if self._worker:

            self._worker.cancel()

        self._reset_ui_state()



    def _on_run_tests(self):

        if not self._current_result or not self._current_result.test_script:

            messagebox.showwarning("无测试脚本", "请先执行探索任务生成测试脚本。")

            return



        self.btn_run.configure(state="disabled", text="执行中...", font=ctk.CTkFont(size=13, weight="bold"))

        self.lbl_status.configure(text="正在执行测试...", text_color="#f59e0b")



        def run_thread():

            try:

                runner = TestRunner()

                result = asyncio.run(runner.run_with_fallback(

                    self._current_result.test_script,

                    self._current_task.id,

                ))

                self._ui_queue.put(("exec_result", result))

            except Exception as e:

                self._ui_queue.put(("exec_result", {"passed": False, "log": str(e)}))



        threading.Thread(target=run_thread, daemon=True).start()



    def _reset_ui_state(self):

        self.btn_start.configure(state="normal", text="开始探索")

        self.btn_stop.configure(state="disabled")

        self._worker = None



    # ── Queue Polling ────────────────────────────



    def _poll_queue(self):

        """Poll the thread-safe queue and update the UI on the main thread."""

        try:

            while True:

                msg = self._ui_queue.get_nowait()

                msg_type, payload = msg

                if msg_type == "step":

                    self._add_step(payload)

                elif msg_type == "log":

                    self._append_log(payload)

                elif msg_type == "snapshot":

                    self._show_screenshot(payload)

                elif msg_type == "reasoning":

                    self._append_log(f"[AI] {payload.get('reasoning', '')}\n")

                elif msg_type == "status":

                    self._update_status(payload)

                elif msg_type == "result":

                    self._show_result(payload)

                elif msg_type == "error":

                    self._append_log(f"[ERROR] {payload}\n")

                    self.lbl_status.configure(text="出错", text_color="#ef4444")

                elif msg_type == "exec_result":

                    self._show_exec_result(payload)

                elif msg_type == "ai_test":

                    self._show_ai_test_result(payload)

        except queue.Empty:

            pass

        self.after(150, self._poll_queue)



    def _add_step(self, step: ExploreStep):

        if self.lbl_步_empty:

            self.lbl_步_empty.destroy()

            self.lbl_步_empty = None



        self._步.append(step)



        card = ctk.CTkFrame(self.步_scroll, corner_radius=8, border_width=1,

                            border_color="gray25", fg_color="#1e2130")

        card.pack(fill="x", padx=4, pady=3)



        status_icon = {"success": "✓", "failed": "✗", "running": "●", "pending": "○", "skipped": "−"}

        status_color = {"success": "#22c55e", "failed": "#ef4444", "running": "#818cf8", "pending": "gray", "skipped": "gray"}

        icon = status_icon.get(step.status.value, "?")

        color = status_color.get(step.status.value, "gray")



        action_map = {"navigate": "导航", "click": "点击", "fill": "输入", "select": "选择",

                      "check": "勾选", "hover": "悬停", "wait": "等待",

                      "assert_visible": "验证可见", "assert_text": "验证文本",

                      "assert_url": "验证地址", "screenshot": "截图"}

        action_label = action_map.get(step.action.value, step.action.value)



        # Header row

        header = ctk.CTkFrame(card, fg_color="transparent")

        header.pack(fill="x", padx=8, pady=(6, 2))

        ctk.CTkLabel(header, text=f"{icon} 步骤 {step.index + 1}",

                     font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),

                     text_color=color).pack(side="left")

        ctk.CTkLabel(header, text=action_label,

                     font=ctk.CTkFont(size=10), text_color="white",

                     fg_color="#2d3148", corner_radius=4).pack(side="left", padx=8)

        if step.duration_ms:

            ctk.CTkLabel(header, text=f"{step.duration_ms}ms",

                         font=ctk.CTkFont(size=10), text_color="white").pack(side="right")



        # Description

        if step.description:

            ctk.CTkLabel(card, text=step.description[:100],

                         font=ctk.CTkFont(family="Segoe UI", size=12), anchor="w", justify="left"

                         ).pack(fill="x", padx=8, pady=(0, 2))



        # Reasoning

        if step.reasoning:

            ctk.CTkLabel(card, text=f"💡 {step.reasoning[:120]}",

                         font=ctk.CTkFont(size=11, slant="italic"),

                         text_color="#818cf8", anchor="w", justify="left"

                         ).pack(fill="x", padx=8)



        # Error — 自适应高度

        if step.error:

            err_text = step.error[:300]

            # 根据文本长度计算行数

            line_count = max(2, min(8, (len(err_text) // 55) + 1))

            err_height = line_count * 18 + 8

            err_frame = ctk.CTkFrame(card, fg_color="#2d1111", corner_radius=4)

            err_frame.pack(fill="x", padx=8, pady=(2, 6))

            err_box = ctk.CTkTextbox(err_frame, height=err_height,

                                     font=ctk.CTkFont(family="Cascadia Code", size=12),

                                     fg_color="#2d1111", text_color="#ef4444",

                                     wrap="word", activate_scrollbars=False)

            err_box.insert("1.0", err_text)

            err_box.configure(state="disabled")

            err_box.pack(fill="x", padx=4, pady=2)



        self._step_widgets.append(card)



        # Auto-scroll

        self.步_scroll._parent_canvas.yview_moveto(1.0)



    def _show_screenshot(self, data: dict):

        try:

            b64 = data.get("screenshot", "")

            if not b64:

                return

            self._latest_screenshot = b64

            img_data = base64.b64decode(b64)

            img = Image.open(io.BytesIO(img_data))



            # Resize to fit tab

            max_w, max_h = 700, 480

            img.thumbnail((max_w, max_h), Image.LANCZOS)



            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)

            self.lbl_screenshot.configure(image=ctk_img, text="",

                                          compound="top")

            self.lbl_screenshot.image = ctk_img  # keep reference



            # Also add URL info

            url = data.get("url", "")

            title = data.get("title", "")

            count = data.get("element_count", 0)

            self.lbl_screenshot.configure(

                text=f"{title}\n{url}\n{count} 个可交互元素")

        except Exception:

            pass



    def _append_log(self, text: str):

        self.text_log.insert("end", text)

        self.text_log.see("end")



    def _update_status(self, data: dict):

        status = data.get("status", "")

        message = data.get("message", "")

        step = data.get("step")

        max_s = data.get("max_步")



        color_map = {

            "starting": "#818cf8", "exploring": "#818cf8", "navigating": "#818cf8",

            "logging_in": "#818cf8", "generating": "#f59e0b", "exploration_done": "#22c55e",

            "completed": "#22c55e", "failed": "#ef4444", "cancelled": "gray",

        }

        color = color_map.get(status, "gray")

        self.lbl_status.configure(text=message, text_color=color)



        # Progress: exploration phase 0-90%, generation phase 90-100%

        if step is not None and max_s:

            # During exploration: actual progress

            pct = min(step / max(max_s, 1), 1.0) * 0.9

            self.progress.set(pct)

        elif status == "generating":

            self.progress.set(0.93)

        elif status in ("exploration_done", "completed"):

            self.progress.set(1.0)

        elif status in ("failed", "cancelled"):

            pass  # keep current



        if status in ("completed", "failed", "cancelled"):

            self._reset_ui_state()





    def _generate_checklist(self, result: TaskResult) -> str:

        """Generate a site feature checklist from exploration 步"""

        # Collect raw data

        pages = []

        clicks = []

        fills = []

        for s in result.步:

            if s.status.value != "success":

                continue

            if s.action.value == "navigate":

                pages.append(s.value or "")

            elif s.action.value == "click":

                clicks.append(s.description)

            elif s.action.value in ("fill", "select"):

                fills.append(s.description)

            elif s.action.value.startswith("assert"):

                pass  # assertions are verification, not features



        unique_pages = list(dict.fromkeys(pages))



        # Try AI summary first

        if settings.AI_API_KEY:

            ai_checklist = self._ai_checklist(unique_pages, clicks, fills)

            if ai_checklist:

                return ai_checklist



        # Fallback: heuristic grouping

        return self._heuristic_checklist(unique_pages, clicks, fills)



    def _ai_checklist(self, pages: list, clicks: list, fills: list) -> str:

        """Use AI to summarize site features"""

        import urllib.request, urllib.error, json

        try:

            summary = chr(10).join([

                "Pages visited: " + ", ".join(pages[:10]),

                "Actions performed: " + ", ".join(clicks[:15]),

                "Form fields used: " + ", ".join(fills[:10]),

            ])

            prompt = f"""Analyze this web exploration data and produce a site feature checklist in Chinese.

Group features by business module (e.g. user management, data management, settings).



Return ONLY a numbered list, one feature per line. Format: "ModuleName: feature description"



{summary}"""



            data = json.dumps({

                "model": settings.AI_MODEL,

                "messages": [

                    {"role":"system","content":"You are a QA analyst. Output only the checklist, no explanation."},

                    {"role":"user","content": prompt},

                ],

                "max_tokens": 500, "temperature": 0.3,

            }).encode("utf-8")



            req = urllib.request.Request(

                settings.AI_API_BASE.rstrip("/") + "/chat/completions",

                data=data,

                headers={"Authorization":"Bearer "+settings.AI_API_KEY,"Content-Type":"application/json"},

            )

            resp = urllib.request.urlopen(req, timeout=20)

            result = json.loads(resp.read())

            content = result["choices"][0]["message"]["content"].strip()



            lines = []

            lines.append("Site Feature Checklist (AI)")

            lines.append("=" * 50)

            lines.append("")

            for line in content.splitlines():

                line = line.strip()

                if line:

                    lines.append(line)

            lines.append("")

            lines.append("-" * 50)

            lines.append("Based on " + str(len(pages)) + " pages explored")

            return chr(10).join(lines)

        except Exception:

            return ""



    def _heuristic_checklist(self, pages: list, clicks: list, fills: list) -> str:

        """Fallback: group features heuristically"""

        from collections import OrderedDict

        modules = OrderedDict()



        # Keyword-based module grouping

        rules = {

            "login": "Login", "register": "Registration",

            "add": "Data Entry", "create": "Data Entry", "new": "Data Entry",

            "edit": "Data Editing", "update": "Data Editing", "modify": "Data Editing",

            "delete": "Data Deletion", "remove": "Data Deletion",

            "search": "Search", "filter": "Search", "query": "Search",

            "upload": "File Management", "download": "File Management",

            "save": "Data Persistence", "submit": "Form Submission",

            "setting": "Settings", "config": "Settings", "profile": "User Profile",

        }



        for action in clicks + fills:

            al = action.lower()

            clean = action

            for prefix in ("click ", "fill ", "select ", "navigate to: "):

                if clean.lower().startswith(prefix):

                    clean = clean[len(prefix):]

            clean = clean.strip().strip("'").strip('"').strip(".")

            if len(clean) < 2:

                continue

            found = False

            for kw, module in rules.items():

                if kw in al:

                    modules.setdefault(module, []).append(clean)

                    found = True

                    break

            if not found:

                modules.setdefault("Other", []).append(clean)



        lines = []

        lines.append("Site Feature Checklist")

        lines.append("=" * 50)

        lines.append("")

        for module, acts in modules.items():

            lines.append(module)

            lines.append("-" * 30)

            seen = set()

            for a in acts:

                short = a[:80].strip()

                if short and short not in seen:

                    seen.add(short)

                    lines.append("  - " + short)

            lines.append("")

        lines.append("-" * 50)

        lines.append("Pages explored: " + str(len(pages)))

        return chr(10).join(lines)





    def _show_result(self, result: TaskResult):

        self._current_result = result



        self.text_feature.delete("1.0", "end")

        self.text_feature.insert("1.0", result.feature_content or "(empty)")



        self.text_script.delete("1.0", "end")

        self.text_script.insert("1.0", result.test_script or "(empty)")



        self.text_po.delete("1.0", "end")

        self.text_po.insert("1.0", result.page_object_code or "(empty)")



        self.btn_run.configure(state="normal")



        # Generate site feature checklist

        checklist = self._generate_checklist(result)

        self.text_checklist.delete("1.0", "end")

        self.text_checklist.insert("1.0", checklist)

        self._append_log("\n" + "="*50 + "\n")
        self._append_log("  任务总结\n")
        self._append_log("="*50 + "\n")
        self._append_log("  网址: " + result.task.target_url + "\n")
        self._append_log("  步数: " + str(len(result.步)) + "  成功: " + str(sum(1 for s in result.步 if s.status.value == "success")) + "  失败: " + str(sum(1 for s in result.步 if s.status.value == "failed")) + "\n")
        self._append_log("  Feature: " + str(len(result.feature_content or "")) + " 字符\n")
        self._append_log("  脚本: " + str(len(result.test_script or "")) + " 字符\n")
        self._append_log("\n  输出文件:\n")
        task_dir = settings.OUTPUT_DIR / result.task.id
        self._append_log("    test.feature       - BDD Feature 文件" + "\n")
        self._append_log("    test_generated.py  - Automated test script" + "\n")
        self._append_log("    page_object.py     - Page Object class" + "\n")
        self._append_log("\n  完整路径: " + str(task_dir) + "\n")
        self._append_log("="*50 + "\n\n")
        
        self.btn_run.configure(state="normal")
        
        checklist = self._generate_checklist(result)
        self.text_checklist.delete("1.0", "end")
        self.text_checklist.insert("1.0", checklist)
        
        self._append_log(f"\n=== 探索完成: {len(result.步)} 步 ===\n")
        self._append_log(f"Feature 文件: {len(result.feature_content or '')} 字符\n")
        self._append_log(f"测试脚本: {len(result.test_script or '')} 字符\n")
        
        self.tab_view.set("探索步骤")





    def _show_ai_test_result(self, data):

        """Display AI connectivity test result"""

        status, msg = data

        from tkinter import messagebox

        if status == "ok":

            self.btn_test_ai.configure(text="连接成功", fg_color="#16a34a", hover_color="#22c55e", state="normal")

            messagebox.showinfo("连接成功", f"AI 服务连接正常!\n模型: {msg}")

        else:

            self.btn_test_ai.configure(text="连接失败", fg_color="#dc2626", hover_color="#ef4444", state="normal")

            messagebox.showerror("连接失败", f"无法连接 AI 服务:\n{msg}")

        # Reset button after 5 seconds

        self.after(5000, lambda: self.btn_test_ai.configure(

            text="测试连接", fg_color="#1e40af", hover_color="#1d4ed8"))



    def _show_exec_result(self, data: dict):

        passed = data.get("passed", False)

        log_text = data.get("log", "")



        self.text_log.delete("1.0", "end")

        self.text_log.insert("1.0", log_text)



        if passed:

            self.lbl_status.configure(text="测试通过", text_color="#22c55e")

            self._append_log("\n=== 全部测试通过 ===\n")

        else:

            self.lbl_status.configure(text="测试失败", text_color="#ef4444")

            self._append_log("\n=== 测试失败 ===\n")



        self.btn_run.configure(state="normal", text="运行生成的测试", font=ctk.CTkFont(size=13, weight="bold"))

        self.tab_view.set("运行日志")





# ══════════════════════════════════════════════════════

#  Entry Point

# ══════════════════════════════════════════════════════



def main():

    # ── 启动环境检查 ──────────────────────────

    import importlib

    issues = []



    # 检查关键模块

    for mod in ("playwright", "customtkinter", "PIL"):

        try:

            importlib.import_module(mod)

        except ImportError:

            issues.append(mod)



    if issues:

        import tkinter as tk

        tk.Tk().withdraw()

        tk.messagebox.showerror(

            "环境错误",

            f"缺少必要模块: {', '.join(issues)}\n\n"

            f"请在命令行运行:\n"

            f"  pip install -r requirements.txt\n"

            f"  python -m playwright install chromium"

        )

        return



    # 检查 Playwright 浏览器

    try:

        from playwright.sync_api import sync_playwright

        p = sync_playwright().start()

        b = p.chromium.launch()

        b.close()

        p.stop()

    except Exception as e:

        import tkinter as tk

        tk.Tk().withdraw()

        tk.messagebox.showerror(

            "浏览器错误",

            f"Playwright 浏览器未安装或启动失败:\n{e}\n\n"

            f"请在命令行运行:\n"

            f"  python -m playwright install chromium"

        )

        return



    app = App()

    app.mainloop()





if __name__ == "__main__":

    main()

