"""EXT-009 Token 预估校准：按模型用 EMA 收敛预估/实际偏差，修正预扣。

只修正 prompt 侧估算；completion 侧预扣维持 max_output_tokens 不变。
样本不足 MIN_SAMPLES 时 ratio 恒为 1.0，避免冷启动误调。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ALPHA = 0.2
MIN_SAMPLES = 5
RATIO_MIN, RATIO_MAX = 0.5, 2.0


def _clamp(x: float) -> float:
    return max(RATIO_MIN, min(RATIO_MAX, x))


async def apply_drift(s: AsyncSession, model_id: int, est_prompt: int) -> int:
    ratio = (await s.execute(text(
        "SELECT ratio FROM model_tokenizer_drift WHERE model_id=:m"),
        {"m": model_id})).scalar_one_or_none()
    if ratio is None:
        return est_prompt
    return max(1, int(round(est_prompt * float(ratio))))


async def update_drift(s: AsyncSession, model_id: int, *,
                       estimated: int, actual: int) -> None:
    if estimated <= 0:
        return
    row = (await s.execute(text(
        "SELECT samples, ratio FROM model_tokenizer_drift WHERE model_id=:m"),
        {"m": model_id})).mappings().first()
    if row is None:
        await s.execute(text(
            "INSERT INTO model_tokenizer_drift (model_id, samples, ratio) "
            "VALUES (:m, 1, 1.0) ON CONFLICT (model_id) DO NOTHING"),
            {"m": model_id})
        return
    samples = int(row["samples"]) + 1
    ratio = float(row["ratio"])
    if samples >= MIN_SAMPLES:
        ratio = _clamp((1 - ALPHA) * ratio + ALPHA * (actual / estimated))
    await s.execute(text(
        "UPDATE model_tokenizer_drift SET samples=:n, ratio=:r, updated_at=now() "
        "WHERE model_id=:m"), {"n": samples, "r": ratio, "m": model_id})