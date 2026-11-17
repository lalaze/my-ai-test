# my-ai-test

基于 [Inspect AI](https://inspect.aisi.org.uk/) 的 AI 测试题库，目前有三类题：

| 任务 | 题型 | 判分方式 |
|---|---|---|
| `evals/quiz.py@choice_questions` | 单选题 | 对比选项字母（默认打乱选项顺序） |
| `evals/quiz.py@short_answer` | 简答题 | 判分模型对照参考答案打分，可以给部分分 |
| `evals/coding.py@coding` | 环境类代码题 | 每题一个 Docker 容器，模型交卷后运行隐藏测试 |

## 准备

1. 安装 [uv](https://docs.astral.sh/uv/) 和 Docker Desktop（跑代码题时 Docker 要处于运行状态）。
2. 安装依赖：`uv sync`
3. 配置 API key：`cp .env.example .env`，然后在 `.env` 里填入 key。Inspect 会自动读取这个文件。

## 运行

```bash
# 选择题
uv run inspect eval evals/quiz.py@choice_questions --model anthropic/claude-sonnet-5-5

# 简答题：建议用一个更强的模型来判分，不指定的话由被测模型自己判
uv run inspect eval evals/quiz.py@short_answer --model anthropic/claude-sonnet-5-5 \
  --model-role grader=anthropic/claude-opus-5-5

# 代码题
uv run inspect eval evals/coding.py --model anthropic/claude-sonnet-5-5

# 查看结果：网页里可以逐题查看模型的回答、执行过的命令和判分理由
uv run inspect view
```

常用参数：

- `--sample-id fix-word-count`：只跑指定的题（多个用逗号分隔）
- `--limit 10`：只跑前 10 道题
- `--epochs 5`：每道题跑 5 遍，看模型是稳定做对还是碰运气做对
- `-T message_limit=100 -T time_limit=1800`：调整代码题的交互轮数和时间上限

兼容 OpenAI 接口的模型（如 DeepSeek）可以写成 `--model openai-api/deepseek/deepseek-chat`，
并在 `.env` 里配置 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_BASE_URL`。

## 目录结构

```
evals/            任务定义（怎么出题、怎么判分）
questions/        选择题、简答题（JSONL 格式，一行一题）
coding_tasks/     代码题，一题一个文件夹
sandbox/          代码题的默认 Docker 环境
```

## 加题

### 选择题：`questions/choice.jsonl`

```json
{"id": "choice-005", "category": "python", "question": "题干", "choices": ["选项A", "选项B", "选项C", "选项D"], "answer": "B"}
```

### 简答题：`questions/short_answer.jsonl`

`answer` 写参考答案和评分要点，判分模型会照着它打分。要点写得越具体，判分越稳定。

```json
{"id": "qa-004", "category": "network", "question": "题干", "answer": "要点：1) ……；2) ……。两点都答到算正确，只答一点算部分正确。"}
```

### 代码题：`coding_tasks/<题目名>/`

```
coding_tasks/fix-word-count/
├── instruction.md    题目描述，原样交给模型
├── workspace/        初始代码，会被拷到容器的 /workspace，模型在这里做题
├── tests/            隐藏测试（pytest），模型交卷后才放进容器
├── solution/         参考答案，会覆盖到 /workspace 上，用来验证题目本身没问题
└── environment/      （可选）这道题专用的 Dockerfile + compose.yaml
```

**每加一道代码题，都先用参考答案验证一遍**。这一步不调用真实模型，不花钱：

```bash
uv run inspect eval evals/coding.py -T oracle_mode=true --model mockllm/model --sample-id <题目名>
```

`resolved` 应该是 1.0。如果不是，说明环境、测试或参考答案有问题。

还要确认原始的 `workspace/` **过不了**全部测试，否则这道题考不出东西。去掉 `oracle_mode`，
直接用模拟模型跑一次，就相当于什么都不改就交卷，这时 `resolved` 应该是 0：

```bash
uv run inspect eval evals/coding.py --model mockllm/model --sample-id <题目名>
```

题目需要额外依赖时（比如 pandas），把 `sandbox/` 下的 `Dockerfile` 和 `compose.yaml` 拷到
这道题的 `environment/` 目录里再修改。注意保留 `agent` 用户和 `network_mode: none` 这两个设置。

## 代码题的判分和防作弊

- 模型以普通用户 `agent` 的身份在 `/workspace` 里做题。容器断网，限制为 1 个 CPU、1GB 内存。
- 模型交卷后，隐藏测试才被拷到只有 root 能访问的 `/grader`，然后以 root 身份运行 pytest。
- 判分时使用 `/grader` 下的配置，并以 `python -I` 方式运行，同时关闭插件自动加载。所以模型在
  `/workspace` 里植入的 `conftest.py`、`pytest.ini`，或者伪造的 `pytest.py`，都不会生效（已用模拟作弊的脚本验证过）。
- 有两个指标：`resolved` 是隐藏测试全部通过的题目比例；`pass_rate` 是平均每道题通过了多少比例的测试，相当于部分分。
- **局限**：被测代码和测试运行在同一个 Python 进程里，所以专门针对判分器设计的攻击（比如在被测模块里篡改 pytest 的内部逻辑）
  理论上仍然可能骗过判分。正式评测时，建议在 `inspect view` 里抽查得分高的记录。
