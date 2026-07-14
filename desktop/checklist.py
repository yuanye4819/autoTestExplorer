"""Site feature checklist generation from exploration results."""
from __future__ import annotations

from models.schemas import TaskResult
from config import settings


def generate_checklist(result: TaskResult) -> str:
    """Generate a site feature checklist from exploration steps."""
    pages = []
    clicks = []
    fills = []
    for s in result.steps:
        if s.status.value != "success":
            continue
        if s.action.value == "navigate":
            pages.append(s.value or "")
        elif s.action.value == "click":
            clicks.append(s.description)
        elif s.action.value in ("fill", "select"):
            fills.append(s.description)

    unique_pages = list(dict.fromkeys(pages))

    if settings.AI_API_KEY:
        ai_result = _ai_checklist(unique_pages, clicks, fills)
        if ai_result:
            return ai_result

    return _heuristic_checklist(unique_pages, clicks, fills)


def _ai_checklist(pages: list, clicks: list, fills: list) -> str:
    """Use AI to summarize site features."""
    import urllib.request, urllib.error, json
    try:
        summary = "\n".join([
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
                {"role": "system", "content": "You are a QA analyst. Output only the checklist, no explanation."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 500, "temperature": 0.3,
        }).encode("utf-8")

        req = urllib.request.Request(
            settings.AI_API_BASE.rstrip("/") + "/chat/completions",
            data=data,
            headers={"Authorization": "Bearer " + settings.AI_API_KEY, "Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=20)
        result = json.loads(resp.read())
        content = result["choices"][0]["message"]["content"].strip()

        lines = ["Site Feature Checklist (AI)", "=" * 50, ""]
        for line in content.splitlines():
            line = line.strip()
            if line:
                lines.append(line)
        lines.extend(["", "-" * 50, "Based on " + str(len(pages)) + " pages explored"])
        return "\n".join(lines)
    except Exception:
        return ""


def _heuristic_checklist(pages: list, clicks: list, fills: list) -> str:
    """Fallback: group features heuristically."""
    from collections import OrderedDict
    modules = OrderedDict()

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

    lines = ["Site Feature Checklist", "=" * 50, ""]
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
    lines.extend(["-" * 50, "Pages explored: " + str(len(pages))])
    return "\n".join(lines)
