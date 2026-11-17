"""知识类题目：选择题 + 简答题。

题目放在 questions/ 下的 JSONL 文件里，一行一道题。
"""

from pathlib import Path
from typing import Any

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, json_dataset
from inspect_ai.scorer import choice, model_graded_qa
from inspect_ai.solver import generate, multiple_choice

QUESTIONS = Path(__file__).parent.parent / "questions"


def _choice_sample(record: dict[str, Any]) -> Sample:
    return Sample(
        id=record["id"],
        input=record["question"],
        choices=record["choices"],
        target=record["answer"],  # 正确选项的字母，如 "B"
        metadata={"category": record.get("category")},
    )


def _short_answer_sample(record: dict[str, Any]) -> Sample:
    return Sample(
        id=record["id"],
        input=record["question"],
        target=record["answer"],  # 参考答案 / 评分要点，交给判分模型对照
        metadata={"category": record.get("category")},
    )


@task
def choice_questions(shuffle_choices: bool = True) -> Task:
    """单选题。默认打乱选项顺序，防止模型靠位置猜答案。"""
    return Task(
        dataset=json_dataset(
            str(QUESTIONS / "choice.jsonl"),
            _choice_sample,
            shuffle_choices=shuffle_choices,
        ),
        solver=multiple_choice(),
        scorer=choice(),
    )


@task
def short_answer() -> Task:
    """简答题，由判分模型对照参考答案打分（C=正确，P=部分正确，I=错误）。

    判分模型用 --model-role grader=<模型> 指定；不指定时由被测模型自己判分。
    """
    return Task(
        dataset=json_dataset(str(QUESTIONS / "short_answer.jsonl"), _short_answer_sample),
        solver=generate(),
        scorer=model_graded_qa(partial_credit=True),
    )
