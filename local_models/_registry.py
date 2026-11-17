"""通过 pyproject.toml 里的 inspect_ai 入口点注册，Inspect 启动时自动加载。"""

from inspect_ai.model import modelapi


@modelapi(name="claude-code")
def claude_code():
    from .cli import ClaudeCodeAPI

    return ClaudeCodeAPI


@modelapi(name="codex")
def codex():
    from .cli import CodexAPI

    return CodexAPI


@modelapi(name="antigravity")
def antigravity():
    from .cli import AntigravityAPI

    return AntigravityAPI
