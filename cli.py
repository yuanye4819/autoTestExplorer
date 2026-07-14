"""Command-line interface for AI Web Exploration Testing System."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from logging_config import setup_logging
from config import settings

setup_logging()


def cmd_serve(args):
    """Start the FastAPI web server."""
    import uvicorn
    host = args.host or settings.HOST
    port = args.port or settings.PORT
    print(f"Starting server at http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=args.reload)


def cmd_explore(args):
    """Run a single exploration from the command line."""
    from state import agent
    from services.exploration import _derive_page_name
    from generators.feature_generator import generate_feature_file
    from generators.script_generator import generate_test_script
    from generators.page_object_generator import generate_page_object
    from models.schemas import ExplorationTask, TaskStatus

    async def _run():
        task = ExplorationTask(
            target_url=args.url,
            requirements=args.requirements or "CLI exploration",
            max_steps=args.steps,
        )
        print(f"Exploring: {task.target_url} ({task.max_steps} steps max)")
        result = await agent.explore(task)
        print(f"Exploration done: {len(result.steps)} steps")

        if result.steps:
            feature = generate_feature_file(task, result.steps)
            script = generate_test_script(task, result.steps)
            po = generate_page_object(result.steps, _derive_page_name(task.target_url))

            out_dir = settings.OUTPUT_DIR / task.id
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "test.feature").write_text(feature, encoding="utf-8")
            (out_dir / "test_generated.py").write_text(script, encoding="utf-8")
            (out_dir / "page_object.py").write_text(po, encoding="utf-8")
            print(f"Output saved to: {out_dir}")
        else:
            print("No steps generated.")

    asyncio.run(_run())


def main():
    parser = argparse.ArgumentParser(description="AI Web Exploration Testing System")
    sub = parser.add_subparsers(dest="command")

    # serve
    p_serve = sub.add_parser("serve", help="Start the web server")
    p_serve.add_argument("--host", help="Bind host")
    p_serve.add_argument("--port", type=int, help="Bind port")
    p_serve.add_argument("--reload", action="store_true", default=True, help="Auto-reload")

    # explore
    p_explore = sub.add_parser("explore", help="Explore a URL from CLI")
    p_explore.add_argument("url", help="Target URL to explore")
    p_explore.add_argument("-r", "--requirements", help="Test requirements (natural language)")
    p_explore.add_argument("-s", "--steps", type=int, default=20, help="Max exploration steps")

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "explore":
        cmd_explore(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
