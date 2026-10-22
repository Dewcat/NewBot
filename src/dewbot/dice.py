from __future__ import annotations

import random
from bisect import bisect_right
from functools import lru_cache
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


@lru_cache(maxsize=512)
def point_advantage(defense: str, attack: str, attack_zero_dice: int = 0) -> dict:
    """P(defense >= attack), independent of battle RNG and damage multipliers."""
    def distribution(expression, zero=0, clamp=False):
        roll_formula(expression, rng=random.Random(0))  # Validate with the same grammar.
        values = {0: 1.0}
        for token in TOKEN.finditer(str(expression).replace(" ", "")):
            sign = -1 if token.group(1) == "-" else 1
            if token.group(3):
                count, faces = int(token.group(2) or 1), int(token.group(3))
                removed = min(zero, count); zero -= removed
                for _ in range(count - removed):
                    if len(values) * faces > 200000:
                        return None
                    next_values = {}
                    for total, probability in values.items():
                        for face in range(1, faces + 1):
                            new_total = total + sign * face
                            next_values[new_total] = next_values.get(new_total, 0.0) + probability / faces
                    values = next_values
            else:
                amount = sign * int(token.group(4))
                values = {total + amount: p for total, p in values.items()}
        # Attack and defense point totals cannot absorb/deal negative damage.
        result = {}
        for total, probability in values.items():
            key = max(0, total) if clamp else total
            result[key] = result.get(key, 0) + probability
        return result
    left, right = distribution(defense), distribution(attack, attack_zero_dice, True)
    approximate = left is None or right is None
    if approximate:
        rng = random.Random(f"{defense}|{attack}|{attack_zero_dice}")
        probability = sum(roll_formula(defense, rng=rng).total >= max(0, roll_formula(attack, rng=rng, zero_dice=attack_zero_dice).total) for _ in range(4096)) / 4096
    else:
        totals = sorted(right); cumulative = []; running = 0
        for total in totals:
            running += right[total]; cumulative.append(running)
        probability = sum(p * (cumulative[bisect_right(totals, total)-1] if bisect_right(totals, total) else 0) for total, p in left.items())
    probability = round(max(0.0, min(1.0, probability)), 10)
    tier = 0 if probability < .2 else 1 if probability < .4 else 2 if probability <= .6 else 3 if probability <= .8 else 4
    return {"probability": round(probability, 6), "tier": tier,
            "label": ["绝对劣势", "劣势", "均势", "优势", "绝对优势"][tier],
            "approximate": approximate, "defense_power": defense, "attack_power": attack,
            "basis": "首段点数比较（同点计入）；不代表反击能否发动"}
