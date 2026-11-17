"""环境类代码题。

每道题是 coding_tasks/ 下的一个文件夹，运行时会启动一个独立的 Docker 容器：

1. 把 workspace/ 拷到容器的 /workspace，交给模型（以普通用户 agent 的身份）用
   bash / python / 文本编辑器去完成；
2. 模型调用 submit() 交卷后，才把 tests/ 里的隐藏测试拷到只有 root 能访问的
   /grader，再以 root 身份运行 pytest 判分。

加 -T oracle_mode=true 时不调用模型，直接用 solution/ 里的参考答案覆盖 /workspace，
用来检查题目本身（环境、测试、参考答案）有没有问题。
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.agent import Agent, react
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Target, accuracy, mean, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import bash, python, text_editor
from inspect_ai.util import sandbox

ROOT = Path(__file__).parent.parent
TASKS_DIR = ROOT / "coding_tasks"
DEFAULT_COMPOSE = ROOT / "sandbox" / "compose.yaml"

WORKSPACE = "/workspace"
GRADER = "/grader"
AGENT_USER = "agent"

AGENT_PROMPT = f"""你在一台 Linux 机器上完成一个编程任务，项目代码位于 {WORKSPACE}。
你可以用 bash、python 和文本编辑器工具查看、修改文件和运行命令。机器没有网络，不能安装新的依赖。
完成后调用 submit() 交卷，提交内容用一两句话说明你做了哪些修改。"""


# ---------------------------------------------------------------- 题目加载


def _files(src: Path, dest: str) -> dict[str, str]:
    """把 src 目录下的所有文件映射到容器内 dest 目录下的对应路径。"""
    if not src.is_dir():
        return {}
    return {
        f"{dest}/{p.relative_to(src).as_posix()}": str(p)
        for p in sorted(src.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def _load_samples() -> list[Sample]:
    samples = []
    for task_dir in sorted(TASKS_DIR.iterdir()):
        if not task_dir.is_dir() or task_dir.name.startswith((".", "_")):
            continue
        # 题目自带环境时用 environment/compose.yaml，否则用 sandbox/ 下的默认环境
        compose = task_dir / "environment" / "compose.yaml"
        samples.append(
            Sample(
                id=task_dir.name,
                input=(task_dir / "instruction.md").read_text(encoding="utf-8"),
                files=_files(task_dir / "workspace", WORKSPACE),
                # 文件是以 root 身份拷进去的，交给 agent 用户之前改一下属主
                setup=f"mkdir -p {WORKSPACE} && chown -R {AGENT_USER}:{AGENT_USER} {WORKSPACE}",
                sandbox=("docker", str(compose)) if compose.exists() else None,
                metadata={"task_dir": str(task_dir)},
            )
        )
    return samples


# ---------------------------------------------------------------- 做题


def coding_agent() -> Agent:
    return react(
        prompt=AGENT_PROMPT,
        tools=[
            bash(timeout=180, user=AGENT_USER),
            python(timeout=180, user=AGENT_USER),
            text_editor(timeout=180, user=AGENT_USER),
        ],
    )


@solver
def oracle() -> Solver:
    """不调用模型，直接把参考答案覆盖到 /workspace。"""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        solution_dir = Path(state.metadata["task_dir"]) / "solution"
        for dest, src in _files(solution_dir, WORKSPACE).items():
            await sandbox().write_file(dest, Path(src).read_bytes())
        return state

    return solve


# ---------------------------------------------------------------- 判分


def _count_results(junit_xml: str) -> tuple[int, int]:
    """从 pytest 的 JUnit XML 报告里数出 (通过数, 总数)。跳过的用例算未通过。"""
    cases = ET.fromstring(junit_xml).iter("testcase")
    total = passed = 0
    for case in cases:
        total += 1
        if not any(child.tag in ("failure", "error", "skipped") for child in case):
            passed += 1
    return passed, total


@scorer(metrics={"resolved": [accuracy()], "pass_rate": [mean()]})
def hidden_tests(timeout: int = 300):
    """resolved：隐藏测试是否全部通过；pass_rate：隐藏测试的通过比例（部分分）。"""

    async def score(state: TaskState, target: Target) -> Score:
        tests_dir = Path(state.metadata["task_dir"]) / "tests"
        sb = sandbox()

        # /grader 只有 root 可读写，agent 用户看不到也改不了里面的测试
        await sb.exec(
            ["bash", "-c", f"rm -rf {GRADER} && mkdir -p {GRADER} && chmod 700 {GRADER}"],
            user="root",
        )
        for dest, src in _files(tests_dir, GRADER).items():
            await sb.write_file(dest, Path(src).read_bytes(), user="root")
        # 用我们自己的配置，忽略 /workspace 里可能被改过的 pytest.ini / pyproject.toml
        await sb.write_file(
            f"{GRADER}/pytest.ini", f"[pytest]\npythonpath = {WORKSPACE}\n", user="root"
        )

        cmd = [
            "python", "-I",  # 隔离模式：不从当前目录加载模块（防止伪造 pytest）
            "-m", "pytest",
            "-c", f"{GRADER}/pytest.ini",
            "--rootdir", GRADER,
            "-p", "no:cacheprovider",
            "--junitxml", f"{GRADER}/junit.xml",
            "-q", GRADER,
        ]
        try:
            result = await sb.exec(
                cmd,
                cwd=WORKSPACE,
                env={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
                user="root",
                timeout=timeout,
            )
        except TimeoutError:
            return Score(
                value={"resolved": 0.0, "pass_rate": 0.0},
                explanation=f"隐藏测试运行超时（超过 {timeout} 秒）",
            )

        try:
            passed, total = _count_results(await sb.read_file(f"{GRADER}/junit.xml"))
        except Exception:
            passed, total = 0, 0

        resolved = result.success and total > 0 and passed == total
        log = (result.stdout + result.stderr).strip()
        return Score(
            value={
                "resolved": 1.0 if resolved else 0.0,
                "pass_rate": passed / total if total else 0.0,
            },
            answer=state.output.completion,
            explanation=f"隐藏测试通过 {passed}/{total}\n\n{log[-3000:]}",
            metadata={"passed": passed, "total": total},
        )

    return score


# ---------------------------------------------------------------- 任务入口


@task
def coding(oracle_mode: bool = False, message_limit: int = 60, time_limit: int = 900) -> Task:
    """环境类代码题。

    Args:
        oracle_mode: 为 True 时用参考答案代替模型，检查题目本身是否正确。
        message_limit: 每道题最多的消息条数，防止模型陷入死循环。
        time_limit: 每道题的最长时间（秒）。
    """
    return Task(
        dataset=_load_samples(),
        solver=oracle() if oracle_mode else coding_agent(),
        scorer=hidden_tests(),
        sandbox=("docker", str(DEFAULT_COMPOSE)),
        message_limit=message_limit,
        time_limit=time_limit,
    )
