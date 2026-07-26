from __future__ import annotations

import random
import re

from .models import RollResult


TOKEN = re.compile(r"([+-]?)(?:(\d*)[dD](\d+)|(\d+))")


class DiceFormulaError(ValueError):
    pass


def roll_formula(
    expression: str | int,
    *,
    rng: random.Random | None = None,
    zero_dice: int = 0,
) -> RollResult:
    """Roll a bounded additive dice expression such as ``2d6+3``.

    ``zero_dice`` implements paralysis. It zeros the first N rolled dice after
    the random results have been produced; the caller is responsible for
    consuming the corresponding paralysis intensity in persistent state.
    """

    source = str(expression).replace(" ", "")
    if not source:
        raise DiceFormulaError("骰子表达式不能为空")
    rng = rng or random.Random()
    position = 0
    constant_total = 0
    rolled: list[tuple[int, int, int]] = []  # sign, value, faces
    detail_parts: list[str] = []

    for match in TOKEN.finditer(source):
        if match.start() != position:
            raise DiceFormulaError(f"无法解析骰子表达式: {source}")
        position = match.end()
        sign = -1 if match.group(1) == "-" else 1
        if match.group(3):
            count = int(match.group(2) or "1")
            faces = int(match.group(3))
            if not 1 <= count <= 100 or not 2 <= faces <= 10_000:
                raise DiceFormulaError("骰子数量需为1-100，面数需为2-10000")
            values = [rng.randint(1, faces) for _ in range(count)]
            rolled.extend((sign, value, faces) for value in values)
        else:
            value = int(match.group(4))
            constant_total += sign * value
    if position != len(source):
        raise DiceFormulaError(f"无法解析骰子表达式: {source}")

    zero_remaining = max(0, zero_dice)
    final_dice: list[tuple[int, int]] = []
    positive = 0
    negative = 0
    dice_total = 0
    for sign, original, faces in rolled:
        value = original
        if zero_remaining > 0:
            value = 0
            zero_remaining -= 1
        dice_total += sign * value
        final_dice.append((value, faces))
        if original == faces:
            positive += 1
        if original == 1:
            negative += 1
        prefix = "-" if sign < 0 else ("+" if detail_parts else "")
        rendered = f"{original}→0" if value == 0 and original != 0 else str(value)
        detail_parts.append(prefix + rendered)

    if constant_total or not rolled:
        prefix = "+" if constant_total >= 0 and detail_parts else ""
        detail_parts.append(f"{prefix}{constant_total}")

    total = dice_total + constant_total
    if not rolled and not detail_parts:
        raise DiceFormulaError(f"无法解析骰子表达式: {source}")
    return RollResult(
        total=total,
        expression=source,
        detail="".join(detail_parts) or str(total),
        dice=final_dice,
        positive_coins=positive,
        negative_coins=negative,
    )
