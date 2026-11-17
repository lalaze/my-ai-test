"""绘图类题目：模型直接输出一段 SVG 代码。

题目放在 questions/svg/ 下，一题一个 Markdown 文件，文件名就是题目 id。
文件开头的 YAML 区块写标准答案和评分要点，正文原样发给模型。

判分分三项：
- valid_svg：能否从回答里提取出一段完整、可以独立打开的 SVG。要求 XML 格式正确、
  声明了 SVG 命名空间、没有引用外部图片或资源，并且浏览器能渲染出来；
- answer_correct：图里是否有一段文字恰好等于标准答案（比如对话气泡里只写了 21）；
- visual：把 SVG 渲染成 PNG，交给多模态判分模型按评分要点逐项打分，折算成 0~1。

渲染出的 SVG 和 PNG 保存在 renders/ 下，可以直接打开查看。
"""

import base64
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessageUser,
    ContentImage,
    ContentText,
    GenerateConfig,
    get_model,
)
from inspect_ai.scorer import Score, Target, accuracy, mean, scorer
from inspect_ai.solver import TaskState, generate

ROOT = Path(__file__).parent.parent
QUESTIONS_DIR = ROOT / "questions" / "svg"
RENDERS_DIR = ROOT / "renders"

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
SVG_RE = re.compile(r"<svg\b.*</svg>", re.S | re.I)
CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]*)", re.I)
# 这些元素的 href 会加载资源（<a> 只是超链接，不算）
LOADING_TAGS = {"image", "use", "feImage", "script"}
RENDER_LONG_SIDE = 1600


# ---------------------------------------------------------------- 题目加载


def _load_question(path: Path) -> Sample:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"{path}：文件开头需要一个用 --- 包起来的 YAML 区块")
    header, body = text[4:].split("\n---\n", 1)
    meta = yaml.safe_load(header) or {}
    return Sample(
        id=path.stem,
        input=body.strip("\n").rstrip(),
        target=str(meta["answer"]),
        metadata={"rubric": list(meta["rubric"])},
    )


# ---------------------------------------------------------------- SVG 检查


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def analyze_svg(completion: str) -> tuple[str | None, ET.Element | None, list[str]]:
    """从回答里提取 SVG 并做静态检查，返回 (SVG 源码, 根元素, 问题列表)。"""
    match = SVG_RE.search(completion)
    if not match:
        return None, None, ["回答里没有找到 <svg>…</svg>"]
    svg = match.group(0)
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        return svg, None, [f"不是合法的 XML，单独打开时浏览器会报错：{e}"]

    problems = []
    if root.tag != f"{{{SVG_NS}}}svg":
        problems.append('根元素没有声明 xmlns="http://www.w3.org/2000/svg"，单独打开时不会显示成图片')
    for el in root.iter():
        refs = []
        if _local(el.tag) in LOADING_TAGS:
            refs += [el.get("href"), el.get(XLINK_HREF)]
        css = " ".join(el.attrib.values())
        if _local(el.tag) == "style" and el.text:
            css += " " + el.text
            if "@import" in el.text:
                problems.append("<style> 里用 @import 引入了外部样式")
        refs += CSS_URL_RE.findall(css)
        for ref in refs:
            ref = (ref or "").strip()
            if ref and not ref.startswith(("#", "data:")):
                problems.append(f"引用了外部资源：{ref[:100]}")
    return svg, root, list(dict.fromkeys(problems))


def svg_texts(root: ET.Element) -> list[str]:
    """图中每个 <text> 元素的文字（合并 <tspan>，压缩空白）。"""
    texts = []
    for el in root.iter():
        if _local(el.tag) == "text":
            text = " ".join("".join(el.itertext()).split())
            if text:
                texts.append(text)
    return texts


# ---------------------------------------------------------------- 渲染


class RenderError(Exception):
    pass


def _render_size(root: ET.Element) -> tuple[int, int] | None:
    """有 viewBox 时把图缩放到长边 1600px；没有 viewBox 时按原始尺寸渲染（返回 None）。"""
    try:
        _, _, w, h = (float(x) for x in re.split(r"[\s,]+", (root.get("viewBox") or "").strip()))
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    k = RENDER_LONG_SIDE / max(w, h)
    return round(w * k), round(h * k)


async def _launch_browser(playwright):
    errors = []
    # 优先用本机的 Chrome（和用户双击打开 SVG 的效果一致），没有再用 Playwright 自带的 Chromium
    for options in ({"channel": "chrome"}, {}):
        try:
            return await playwright.chromium.launch(**options)
        except Exception as e:
            errors.append(str(e).splitlines()[0])
    raise RuntimeError(
        "找不到可以渲染 SVG 的浏览器。请安装 Google Chrome，"
        "或者运行 uv run playwright install chromium --only-shell\n" + "\n".join(errors)
    )


async def render_png(svg: str, size: tuple[int, int] | None) -> bytes:
    """用浏览器把 SVG 当作一张独立图片渲染成 PNG。

    通过 <img> 加载：浏览器会按独立的 SVG 文件解析，不执行脚本，也不加载任何外部资源。
    """
    from playwright.async_api import async_playwright

    src = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    style = f"width:{size[0]}px;height:{size[1]}px" if size else ""
    html = f'<body style="margin:0;background:#fff"><img id="art" style="{style}" src="{src}"></body>'

    async with async_playwright() as p:
        browser = await _launch_browser(p)
        try:
            page = await browser.new_page(viewport={"width": 2400, "height": 2400})
            await page.route("**/*", lambda route: route.abort())
            await page.set_content(html)
            loaded = await page.evaluate(
                """() => {
                    const img = document.getElementById('art');
                    return img.decode().then(() => img.naturalWidth > 0, () => false);
                }"""
            )
            if not loaded:
                raise RenderError("浏览器无法把它当作 SVG 图片渲染出来")
            return await page.locator("#art").screenshot()
        finally:
            await browser.close()


# ---------------------------------------------------------------- 画面评分


JUDGE_PROMPT = """你是一名严格的评审。上面这张图是 AI 按照下面的题目要求，用 SVG 代码画出来的（已经渲染成图片）。

【题目要求】
{prompt}

【标准答案】对话气泡里应该只有数字 {answer}。

【图中所有 <text> 元素的文字】
{texts}

请对照图片逐项检查下面的评分要点，每项打 0、1 或 2 分：
- 0 分：没有做到，或者画错了；
- 1 分：部分做到，或者画得含糊、难以辨认；
- 2 分：清楚地做到了。
如果某个角色只是用文字标签表示、并没有真的画出来，涉及这个角色的项目都打 0 分。

【评分要点】
{rubric}

只输出 JSON，不要输出其他内容，格式如下：
{{"items": [{{"id": 1, "score": 2, "reason": "一句话理由"}}]}}"""


async def judge_image(
    prompt: str, answer: str, rubric: list[str], texts: list[str], png: bytes
) -> tuple[float, str]:
    """让判分模型看图打分，返回 (0~1 的分数, 逐项说明)。判分模型由 --model-role grader=... 指定。"""
    message = ChatMessageUser(
        content=[
            ContentImage(image="data:image/png;base64," + base64.b64encode(png).decode(), detail="high"),
            ContentText(
                text=JUDGE_PROMPT.format(
                    prompt=prompt,
                    answer=answer,
                    texts="\n".join(f"- {t}" for t in texts) or "（没有）",
                    rubric="\n".join(f"{i}. {r}" for i, r in enumerate(rubric, 1)),
                )
            ),
        ]
    )
    raw = (await get_model(role="grader").generate([message])).completion
    try:
        data = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
        items = {
            int(item["id"]): (max(0, min(2, int(item["score"]))), str(item.get("reason", "")))
            for item in data["items"]
        }
    except (ValueError, KeyError, TypeError):
        return math.nan, f"判分模型的输出无法解析：{raw[:300]}"

    total, lines = 0, []
    for i, criterion in enumerate(rubric, 1):
        points, reason = items.get(i, (0, "判分模型漏评了这一项，按 0 分算"))
        total += points
        lines.append(f"{i}. [{points}/2] {criterion}\n   {reason}")
    return total / (2 * len(rubric)), "\n".join(lines)


# ---------------------------------------------------------------- 判分


def _save_render(state: TaskState, svg: str, png: bytes | None) -> Path:
    model = re.sub(r"[^\w.-]+", "_", str(state.model))
    out_dir = RENDERS_DIR / model / str(state.sample_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"epoch{state.epoch}-{str(state.uuid)[:8]}"
    stem.with_suffix(".svg").write_text(svg, encoding="utf-8")
    if png is not None:
        stem.with_suffix(".png").write_bytes(png)
    return stem


@scorer(metrics={"valid_svg": [accuracy()], "answer_correct": [accuracy()], "visual": [mean()]})
def svg_scorer():
    async def score(state: TaskState, target: Target) -> Score:
        answer = target.text
        notes = []
        if state.output.stop_reason == "max_tokens":
            notes.append("⚠️ 回答达到长度上限被截断了，可以用 -T max_tokens=... 调大")

        svg, root, problems = analyze_svg(state.output.completion)
        texts = svg_texts(root) if root is not None else []

        png = None
        if root is not None:
            try:
                png = await render_png(svg, _render_size(root))
            except RenderError as e:
                problems.append(str(e))

        if png is not None:
            visual, judge_notes = await judge_image(
                state.input_text, answer, state.metadata["rubric"], texts, png
            )
        else:
            visual, judge_notes = 0.0, "SVG 没能渲染出来，画面按 0 分算"

        valid = not problems and png is not None
        answer_ok = answer in texts
        saved = _save_render(state, svg, png) if svg else None

        explanation = "\n\n".join(
            [
                *notes,
                "**SVG 检查**：" + ("通过" if valid else "不通过\n" + "\n".join(f"- {p}" for p in problems)),
                f"**气泡答案**：标准答案 {answer}，图中文字 {texts or '（没有）'} → "
                + ("正确" if answer_ok else "错误"),
                f"**画面评分**：{visual:.2f}\n{judge_notes}",
                f"**渲染文件**：{saved.relative_to(ROOT)}.svg / .png" if saved else "",
            ]
        ).strip()
        return Score(
            value={
                "valid_svg": 1.0 if valid else 0.0,
                "answer_correct": 1.0 if answer_ok else 0.0,
                "visual": visual,
            },
            answer=f"{len(svg)} 字符的 SVG" if svg else state.output.completion[:200],
            explanation=explanation,
            metadata={"texts": texts, "problems": problems},
        )

    return score


# ---------------------------------------------------------------- 任务入口


@task
def svg_drawing(max_tokens: int = 16000) -> Task:
    """绘图题。

    Args:
        max_tokens: 模型单次回答的长度上限。详细的 SVG 往往很长，模型不支持时可以调小。
    """
    return Task(
        dataset=[_load_question(p) for p in sorted(QUESTIONS_DIR.glob("*.md"))],
        solver=generate(),
        scorer=svg_scorer(),
        config=GenerateConfig(max_tokens=max_tokens),
    )
