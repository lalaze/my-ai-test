# my-ai-test

基于 [Inspect AI](https://inspect.aisi.org.uk/) 的 AI 测试题库。

## 当前题库

| 题型 | 任务 | 题目位置 | 题数 |
|---|---|---|---|
| 绘图题（输出 SVG） | `evals/svg.py` | `questions/svg/*.md` | 1 |
| 单选题 | `evals/quiz.py@choice_questions` | `questions/choice.jsonl` | 0 |
| 简答题 | `evals/quiz.py@short_answer` | `questions/short_answer.jsonl` | 0 |
| 环境类代码题 | `evals/coding.py` | `coding_tasks/` | 0 |

题数为 0 的题型直接运行会报 `The specified dataset is empty`，加了题之后就能用。

## 准备

1. 安装 [uv](https://docs.astral.sh/uv/)。
2. 绘图题要用浏览器把 SVG 渲染成图片：装了 Google Chrome 就行。没有 Chrome 的话，运行一次
   `uv run playwright install chromium --only-shell`。
3. 代码题需要 Docker Desktop，并且运行时要处于启动状态。
4. 安装依赖：`uv sync`
5. 选择怎么调用模型，二选一：
   - **用 API**：`cp .env.example .env`，然后在 `.env` 里填写 API key。Inspect 会自动读取这个文件。
   - **用本机的 Claude Code / Codex / Antigravity**（用订阅额度，不需要 API key）：先确认 `claude`、`codex`、`agy` 都已经登录，
     详见下面的「用本机的 Claude Code / Codex / Antigravity 跑题」。

## 运行

```bash
# 绘图题：判分模型要能看图，建议指定一个强的多模态模型
uv run inspect eval evals/svg.py --model anthropic/claude-sonnet-5-5 \
  --model-role grader=anthropic/claude-opus-5-5

# 单选题 / 简答题 / 代码题
uv run inspect eval evals/quiz.py@choice_questions --model anthropic/claude-sonnet-5-5
uv run inspect eval evals/quiz.py@short_answer --model anthropic/claude-sonnet-5-5 \
  --model-role grader=anthropic/claude-opus-5-5
uv run inspect eval evals/coding.py --model anthropic/claude-sonnet-5-5
```

不指定 `--model-role grader=...` 时，由被测模型给自己判分，这样不太客观。

常用参数：

- `--sample-id pelican-wing-candy`：只跑指定的题（多个用逗号分隔）
- `--epochs 5`：每道题跑 5 遍，看模型是稳定做对还是碰运气做对
- `-T max_tokens=8000`：绘图题的回答长度上限，默认 16000。模型不支持这么长时调小
- `-T message_limit=100 -T time_limit=1800`：代码题的交互轮数和时间上限

兼容 OpenAI 接口的模型（如 DeepSeek）可以写成 `--model openai-api/deepseek/deepseek-chat`，
并在 `.env` 里配置 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_BASE_URL`。

### 用本机的 Claude Code / Codex / Antigravity 跑题

`local_models/` 把本机已登录的 `claude -p`、`codex exec` 和 Google 的 `agy -p`（Antigravity）包装成了 Inspect 模型，
用的是你的订阅额度：

```bash
# Claude 答题，Claude Opus 判分
uv run inspect eval evals/svg.py --model claude-code/sonnet --model-role grader=claude-code/opus

# Codex / Gemini 答题，同样用 Claude Opus 判分
uv run inspect eval evals/svg.py --model codex/gpt-6.1-sol --model-role grader=claude-code/opus
uv run inspect eval evals/svg.py --model antigravity/gemini-4-carbon-high --model-role grader=claude-code/opus
```

| 写法 | 说明 |
|---|---|
| `claude-code/sonnet`、`claude-code/opus`、`claude-code/fable` | 别名对应 Claude Code 里的最新模型，也可以写完整的模型名 |
| `claude-code/default` | Claude Code 当前的默认模型 |
| `codex/<模型名>` | 比如 `codex/gpt-6.1-sol`；`codex/default` 表示 Codex 内置的默认模型（不读你的配置文件） |
| `antigravity/<模型名>` | 可选模型用 `agy models` 查看，比如 `antigravity/gemini-4-carbon-high`；`antigravity/default` 表示 Antigravity 当前的默认模型 |

需要注意：

- **不支持工具调用**：绘图题、选择题、简答题可以跑，**代码题不能跑**。
- **Antigravity 只支持文字输入**：它的命令行不接收图片，所以不能用来当绘图题的判分模型。判分请用 `claude-code/...`，
  或者用 Gemini API（见下方）。
- 这些 CLI 本身都是 agent 产品，这里尽量让它们「直接回答」：
  - **Claude Code**：用 `--safe-mode` 关掉了 CLAUDE.md、hooks、MCP 等个人配置，禁用了所有工具，并换成中性的系统提示词。
  - **Codex**：忽略你的 `config.toml`，在只读沙箱里运行，但它自带的系统提示词去不掉。
  - **Antigravity**：工具和系统提示词都没法从命令行关掉（自带的提示词约 1 万 token）。只能在临时空目录和 `--sandbox` 里运行，
    并在题目前加一句「直接回答，不要用工具、不要创建文件」。
  - 因此跑出来的结果和直接调用 API 不完全等价，Antigravity 的偏差最大。
- 每个模型同时最多跑 2 道题，以免很快碰到订阅的频率限制。单次调用超过 20 分钟（Antigravity 为 30 分钟）会判为超时。
- Codex 提示 `refresh token was revoked` 时，在终端里运行 `codex logout && codex login` 重新登录。

**想用 Gemini 看图判分**：可以用 Inspect 自带的 Google 接口。先运行 `uv add google-genai`，在 `.env` 里填写
`GOOGLE_API_KEY`（可以在 Google AI Studio 申请），再用 `--model-role grader=google/<模型名>`。

## 看结果

- **终端**：每次运行结束都会打印总分。
- **网页**：`uv run inspect view` 会打开 http://127.0.0.1:7575 。在那里可以看到每次运行的分数；点进去能看到每道题的
  题目、模型的完整回答、判分理由，以及判分模型看到的图片。
- **绘图题的图**：保存在 `renders/<模型>/<题目 id>/` 下，每次作答一个 `.svg`（模型原始输出）和一个 `.png`（渲染结果），可以直接打开看。

`logs/` 和 `renders/` 都已加进 `.gitignore`，不会被提交。

## 加题

### 绘图题：`questions/svg/<题目 id>.md`

一题一个文件，文件名就是题目 id。开头的 YAML 区块写标准答案和评分要点，`---` 后面的正文原样发给模型：

```markdown
---
answer: "21"          # 图中必须出现、并且单独成为一段文字的答案
rubric:               # 判分模型逐项打分，每项 0~2 分
  - 第一个要检查的画面要点
  - 第二个要检查的画面要点
---

Please create a detailed SVG image ...
```

评分要点写得越具体越好，比如写明「能认出是孙悟空：猴脸、金箍等特征」，判分会更稳定。

### 单选题：在 `questions/choice.jsonl` 里加一行

```json
{"id": "choice-001", "category": "python", "question": "题干", "choices": ["选项A", "选项B", "选项C", "选项D"], "answer": "B"}
```

### 简答题：在 `questions/short_answer.jsonl` 里加一行

`answer` 写参考答案和评分要点：

```json
{"id": "qa-001", "category": "network", "question": "题干", "answer": "要点：1) ……；2) ……。两点都答到算正确，只答一点算部分正确。"}
```

JSONL 文件里一题只占一行，题干需要换行时写 `\n`，`id` 不能重复。

### 代码题：`coding_tasks/<题目 id>/`

```
coding_tasks/<题目 id>/
├── instruction.md    题目描述，原样交给模型
├── workspace/        初始代码，会被拷到容器的 /workspace，模型在这里做题
├── tests/            隐藏测试（pytest），模型交卷后才放进容器
├── solution/         参考答案，会覆盖到 /workspace 上，用来验证题目本身没问题
└── environment/      （可选）这道题专用的 Dockerfile + compose.yaml
```

每加一道代码题，都先跑两遍自检。这两步都不调用真实模型，不花钱：

```bash
# 用参考答案跑：resolved 应该是 1.0，说明环境、测试和参考答案都没问题
uv run inspect eval evals/coding.py -T oracle_mode=true --model mockllm/model --sample-id <题目 id>
# 不改代码直接交卷：resolved 应该是 0，说明这道题能考出东西
uv run inspect eval evals/coding.py --model mockllm/model --sample-id <题目 id>
```

题目需要额外依赖时（比如 pandas），把 `sandbox/` 下的 `Dockerfile` 和 `compose.yaml` 拷到这道题的
`environment/` 目录里再修改。注意保留 `agent` 用户和 `network_mode: none` 这两个设置。

## 判分说明

### 绘图题

| 指标 | 含义 |
|---|---|
| `valid_svg` | 能否从回答里提取出可以独立打开的 SVG：XML 合法、声明了 `xmlns="http://www.w3.org/2000/svg"`、没有引用外部图片或资源，并且浏览器能渲染出来 |
| `answer_correct` | 图中是否有一个 `<text>` 元素的文字恰好等于标准答案（会合并 `<tspan>`）。写成 `答案是 21` 不算，因为题目要求气泡里只有数字 |
| `visual` | 判分模型看渲染图，按 rubric 逐项打 0/1/2 分，折算成 0~1。角色用文字标签代替、没有真的画出来的，相关项记 0 分 |

渲染时，SVG 是作为一张独立图片加载进浏览器的，不会执行里面的脚本，也不会加载外部资源。

`visual` 依赖判分模型的眼光，会有波动。建议用比被测模型更强的模型来判分，再加上 `--epochs` 多跑几遍取平均。
如果模型用路径（path）而不是 `<text>` 来画数字，`answer_correct` 会记为 0，但 rubric 里关于气泡的那一项仍然会由判分模型看图判断。

### 代码题

- 模型以普通用户 `agent` 的身份在 `/workspace` 里做题。容器断网，限制为 1 个 CPU、1GB 内存。
- 模型交卷后，隐藏测试才被拷到只有 root 能访问的 `/grader`，然后以 root 身份运行 pytest。
  判分时用的是 `/grader` 下的配置，并以 `python -I` 运行、关闭插件自动加载。所以模型在 `/workspace` 里放的
  `conftest.py`、`pytest.ini` 或者伪造的 `pytest.py` 都不会生效（已验证）。
- 有两个指标：`resolved` 是隐藏测试全部通过的题目比例；`pass_rate` 是平均每道题的测试通过比例，相当于部分分。
- 局限：被测代码和测试运行在同一个 Python 进程里，专门针对判分器设计的攻击理论上仍然可能骗过判分。
  正式评测时，建议在 `inspect view` 里抽查得分高的记录。
