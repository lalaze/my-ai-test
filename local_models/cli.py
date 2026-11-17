"""把本机已登录的 Claude Code（claude -p）、Codex（codex exec）和 Google Antigravity（agy -p）
当成 Inspect 模型来用。

用的是命令行工具自己的登录（订阅额度），不需要 API key：

    --model claude-code/sonnet              # 也可以写 opus、fable，或者完整的模型名
    --model claude-code/default             # 用 Claude Code 当前的默认模型
    --model codex/gpt-6.1-sol
    --model codex/default
    --model antigravity/gemini-4-carbon-high   # 可选模型见 agy models
    --model antigravity/default

限制：
- 不支持 Inspect 的工具调用，所以不能用来跑代码题（agent 题）。
- Claude Code 和 Codex 支持文字 + 图片；Antigravity 只支持文字（它的命令行不接收图片），不能当看图的判分模型。
- 这些 CLI 都是 agent 产品，这里尽量把它们调成「直接回答」的状态：Claude Code 用 --safe-mode
  关掉 CLAUDE.md、hooks、MCP 等个人配置，禁用所有工具，并换成中性的系统提示词；Codex 忽略用户配置、
  只读沙箱运行；Antigravity 的工具和系统提示词关不掉，只能在空目录 + 沙箱里运行，并在题目前提示它直接回答。
  所以结果和直接调用 API 不完全等价，Antigravity 偏差最大。
"""

import asyncio
import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ContentImage,
    ContentText,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.tool import ToolChoice, ToolInfo

DEFAULT_TIMEOUT = 1200  # 秒；画一张详细的 SVG 可能要好几分钟
NEUTRAL_SYSTEM_PROMPT = "You are a helpful assistant."
IMAGE_SUFFIX = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}


# ---------------------------------------------------------------- 公共工具


def _flatten(messages: list[ChatMessage]) -> tuple[str | None, list[ContentText | ContentImage]]:
    """把 Inspect 的对话转成 (系统提示词, 一条用户消息的内容)。

    CLI 每次调用只接收一条消息，多轮对话会按角色加上标记后拼在一起。
    """
    system = "\n\n".join(m.text for m in messages if isinstance(m, ChatMessageSystem)) or None
    turns = [m for m in messages if not isinstance(m, ChatMessageSystem)]
    parts: list[ContentText | ContentImage] = []
    for m in turns:
        if len(turns) > 1:
            parts.append(ContentText(text=f"[{'Assistant' if isinstance(m, ChatMessageAssistant) else 'User'}]"))
        for c in [ContentText(text=m.content)] if isinstance(m.content, str) else m.content:
            if isinstance(c, (ContentText, ContentImage)):
                parts.append(c)
            elif getattr(c, "type", None) != "reasoning":
                raise ValueError(f"本地 CLI 模型不支持 {c.type} 类型的输入")
    return system, parts


def _image_bytes(image: str) -> tuple[str, bytes]:
    """把 ContentImage 里的图片（data URL 或本地路径）转成 (MIME 类型, 字节)。"""
    if image.startswith("data:"):
        header, data = image.split(",", 1)
        return header[5:].split(";")[0], base64.b64decode(data)
    path = Path(image)
    media_type = {v: k for k, v in IMAGE_SUFFIX.items()}.get(path.suffix.lower(), "image/png")
    return media_type, path.read_bytes()


def _reject_tools(tools: list[ToolInfo]) -> None:
    if tools:
        raise RuntimeError("本地 CLI 模型（claude-code / codex）不支持 Inspect 的工具调用，代码题请改用 API 模型")


async def _run(cmd: list[str], stdin: str, cwd: str, env: dict[str, str], timeout: int) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin.encode()), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"{cmd[0]} 超过 {timeout} 秒没有返回")
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _json_lines(text: str) -> list[dict[str, Any]]:
    events = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


# ---------------------------------------------------------------- Claude Code


class ClaudeCodeAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(model_name=model_name, base_url=base_url, api_key=api_key, config=config)
        self.timeout = int(model_args.get("timeout", DEFAULT_TIMEOUT))

    def max_connections(self) -> int:
        return 2  # 同时跑太多会很快碰到订阅的频率限制

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        _reject_tools(tools)
        system, parts = _flatten(input)

        content = []
        for p in parts:
            if isinstance(p, ContentText):
                content.append({"type": "text", "text": p.text})
            else:
                media_type, data = _image_bytes(p.image)
                content.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode()},
                    }
                )
        message = {"type": "user", "message": {"role": "user", "content": content}}

        cmd = [
            "claude", "-p",
            "--safe-mode",            # 不加载 CLAUDE.md、hooks、MCP、skills 等个人配置
            "--tools", "",            # 禁用所有内置工具，只能直接回答
            "--system-prompt", system or NEUTRAL_SYSTEM_PROMPT,
            "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose",
            "--no-session-persistence",
        ]  # fmt: skip
        if self.model_name != "default":
            cmd += ["--model", self.model_name]

        # 在 Claude Code 里面运行评测时，去掉这个变量，否则子进程会拒绝启动
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        if config.max_tokens:
            env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(config.max_tokens)

        with tempfile.TemporaryDirectory(prefix="claude-code-") as cwd:
            code, out, err = await _run(cmd, json.dumps(message) + "\n", cwd, env, self.timeout)

        result = next((e for e in reversed(_json_lines(out)) if e.get("type") == "result"), None)
        if result is None or result.get("is_error") or code != 0:
            detail = (result or {}).get("result") or err.strip() or out.strip()
            raise RuntimeError(f"claude -p 调用失败（退出码 {code}）：{detail[-1000:]}")

        usage = result.get("usage") or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_write = usage.get("cache_creation_input_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        actual_model = next(iter(result.get("modelUsage") or {}), self.model_name)

        output = ModelOutput.from_content(model=actual_model, content=result.get("result", ""))
        output.usage = ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens + cache_write + cache_read,
            input_tokens_cache_write=cache_write,
            input_tokens_cache_read=cache_read,
        )
        return output


# ---------------------------------------------------------------- Codex


class CodexAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(model_name=model_name, base_url=base_url, api_key=api_key, config=config)
        self.timeout = int(model_args.get("timeout", DEFAULT_TIMEOUT))

    def max_connections(self) -> int:
        return 2

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        _reject_tools(tools)
        system, parts = _flatten(input)

        with tempfile.TemporaryDirectory(prefix="codex-") as cwd:
            texts, images = [system] if system else [], []
            for p in parts:
                if isinstance(p, ContentText):
                    texts.append(p.text)
                else:
                    media_type, data = _image_bytes(p.image)
                    path = Path(cwd) / f"image-{len(images) + 1}{IMAGE_SUFFIX.get(media_type, '.png')}"
                    path.write_bytes(data)
                    images.append(str(path))

            last_message = Path(cwd) / "last-message.txt"
            cmd = [
                "codex", "exec",
                "--ignore-user-config",   # 不加载 ~/.codex/config.toml（MCP 服务器等）
                "--ephemeral",            # 不保存会话
                "--skip-git-repo-check",
                "--sandbox", "read-only",
                "--cd", cwd,
                "--output-last-message", str(last_message),
                "--json",
                "--color", "never",
            ]  # fmt: skip
            if self.model_name != "default":
                cmd += ["--model", self.model_name]
            if config.reasoning_effort:
                cmd += ["--config", f"model_reasoning_effort={config.reasoning_effort}"]
            cmd += [f"--image={path}" for path in images]
            cmd += ["-"]  # 从标准输入读题目

            code, out, err = await _run(cmd, "\n\n".join(texts), cwd, dict(os.environ), self.timeout)
            answer = last_message.read_text(encoding="utf-8") if last_message.exists() else ""

        events = _json_lines(out)
        if code != 0 or not answer:
            errors = [e.get("message") or json.dumps(e)[:300] for e in events if e.get("type") in ("error", "turn.failed")]
            detail = "\n".join(errors) or err.strip()[-1000:] or out.strip()[-1000:]
            raise RuntimeError(f"codex exec 调用失败（退出码 {code}）：{detail}")

        usage = next((e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed"), None) or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        output = ModelOutput.from_content(model=f"codex/{self.model_name}", content=answer)
        output.usage = ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            input_tokens_cache_read=usage.get("cached_input_tokens"),
            reasoning_tokens=usage.get("reasoning_output_tokens"),
        )
        return output


# ---------------------------------------------------------------- Google Antigravity


# Antigravity 的工具没法从命令行关掉，只能提示它直接作答（相当于 Claude Code 的 --tools ""）
ANTIGRAVITY_DIRECT_ANSWER = "Answer directly in your reply. Do not use any tools and do not create any files."


class AntigravityAPI(ModelAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        super().__init__(model_name=model_name, base_url=base_url, api_key=api_key, config=config)
        self.timeout = int(model_args.get("timeout", 1800))  # Antigravity 明显更慢

    def max_connections(self) -> int:
        return 2

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        _reject_tools(tools)
        system, parts = _flatten(input)
        if any(isinstance(p, ContentImage) for p in parts):
            raise RuntimeError("Antigravity 命令行不支持图片输入，看图判分请用 claude-code/... 或 API 模型")

        prompt = "\n\n".join([ANTIGRAVITY_DIRECT_ANSWER, *([system] if system else []), *(p.text for p in parts)])
        # 用 stream-json 从标准输入传题目，避免超长的命令行参数
        message = {"event": "user", "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}}
        cmd = [
            "agy",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--disable-slash-commands",
            "--sandbox",
            "--print-timeout", f"{self.timeout}s",
        ]  # fmt: skip
        if self.model_name != "default":
            cmd += ["--model", self.model_name]
        if config.reasoning_effort in ("low", "medium", "high", "xhigh", "max"):
            cmd += ["--effort", config.reasoning_effort]
        cmd += ["-p="]  # 题目来自标准输入；-p 后面必须紧跟 =，否则会把下一个参数当成题目

        with tempfile.TemporaryDirectory(prefix="antigravity-") as cwd:
            code, out, err = await _run(cmd, json.dumps(message) + "\n", cwd, dict(os.environ), self.timeout + 60)

        events = _json_lines(out)
        init = next((e.get("init") or {} for e in events if e.get("event") == "init"), {})
        result = next((e.get("result") or {} for e in reversed(events) if e.get("event") == "result"), {})
        if result.get("status") != "SUCCESS" or not result.get("response"):
            detail = result.get("error") or err.strip()[-1000:] or out.strip()[-1000:]
            raise RuntimeError(f"agy 调用失败（退出码 {code}）：{detail}")

        usage = result.get("usage") or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        output = ModelOutput.from_content(model=init.get("model") or self.model_name, content=result["response"])
        output.usage = ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=usage.get("total_tokens") or input_tokens + output_tokens,
            input_tokens_cache_read=usage.get("cache_read_tokens"),
            reasoning_tokens=usage.get("thinking_tokens"),
        )
        return output
