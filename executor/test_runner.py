"""
测试执行器 — 运行生成的自动化测试脚本并收集执行结果
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from config import settings


class TestRunner:
    """
    测试执行器：
    - 将生成的测试脚本写入临时文件
    - 使用 pytest + pytest-playwright 执行
    - 收集输出日志和执行结果
    """

    def __init__(self):
        self._on_output: Optional[Callable] = None

    def on_output(self, callback: Callable):
        """设置输出回调（用于 WebSocket 实时推送）"""
        self._on_output = callback

    async def _write_output(self, text: str):
        if self._on_output:
            await self._on_output(text)

    async def run_test_script(
        self,
        script_content: str,
        task_id: str,
        headed: bool = True,
    ) -> dict:
        """
        运行测试脚本并返回结果。

        参数:
            script_content: 测试脚本的完整 Python 代码
            task_id: 关联的任务 ID
            headed: 是否使用有头浏览器

        返回:
            {
                "passed": bool,
                "log": str,
                "output": str,
                "duration_seconds": float,
            }
        """
        await self._write_output(f"🚀 开始执行测试脚本 (Task: {task_id})...\n")

        # 创建临时目录存放脚本
        test_dir = settings.OUTPUT_DIR / task_id
        test_dir.mkdir(parents=True, exist_ok=True)
        script_path = test_dir / "test_generated.py"

        # 写入脚本
        script_path.write_text(script_content, encoding="utf-8")
        await self._write_output(f"📝 测试脚本已写入: {script_path}\n")

        # 构建执行命令
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        cmd = [
            "python", "-m", "pytest",
            str(script_path),
            "-v",                          # 详细输出
            "--tb=short",                   # 简短回溯
            "--color=no",                    # 无颜色（便于日志）
            "-p", "pytest_playwright",       # 启用 Playwright 插件
        ]
        if headed:
            cmd.append("--headed")           # 有头模式（仅 flag，不需要 =true）

        await self._write_output(f"⚙️ 执行命令: {' '.join(cmd)}\n\n")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=str(settings.PROJECT_ROOT),
            )

            output_lines = []
            async for line in process.stdout:
                text = line.decode("utf-8", errors="replace")
                output_lines.append(text)
                await self._write_output(text)

            await process.wait()

            full_output = "".join(output_lines)
            passed = process.returncode == 0

            await self._write_output(f"\n{'✅' if passed else '❌'} 测试{'通过' if passed else '失败'}\n")

            return {
                "passed": passed,
                "log": full_output,
                "output": full_output,
                "return_code": process.returncode,
            }

        except FileNotFoundError:
            error_msg = "❌ 未找到 pytest。请确保已安装: pip install pytest pytest-playwright\n"
            await self._write_output(error_msg)
            return {
                "passed": False,
                "log": error_msg,
                "output": error_msg,
                "return_code": -1,
            }
        except Exception as e:
            error_msg = f"❌ 执行异常: {e}\n"
            await self._write_output(error_msg)
            return {
                "passed": False,
                "log": error_msg,
                "output": error_msg,
                "return_code": -1,
            }

    async def run_with_fallback(self, script_content: str, task_id: str) -> dict:
        """Run headless first; retry headed only for debugging visibility."""
        # First: headless mode (faster, more reliable in CI)
        result = await self.run_test_script(script_content, task_id, headed=False)

        if not result["passed"]:
            await self._write_output("\nRetrying with headed mode for debugging...\n")
            # Second: headed mode (useful for visual debugging)
            result = await self.run_test_script(script_content, task_id, headed=True)

        return result
