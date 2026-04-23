# -*- coding: utf-8 -*-
"""
来财 (Attract-wealth) — 统一 Pydantic Schema 契约
解决 snake_case (后端) 与 camelCase (前端) 的自动转换问题。
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


_CAMEL_BOUNDARY_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_BOUNDARY_2 = re.compile(r"([a-z0-9])([A-Z])")


def _camel_to_snake(field_name: str) -> str:
    text = str(field_name or "").strip()
    if not text:
        return text
    step1 = _CAMEL_BOUNDARY_1.sub(r"\1_\2", text)
    step2 = _CAMEL_BOUNDARY_2.sub(r"\1_\2", step1)
    return step2.replace("-", "_").lower()


class BaseSchema(BaseModel):
    """
    基础 Schema 类。
    - 自动将 snake_case 字段映射为 camelCase 供前端使用。
    - 允许通过 snake_case 或 camelCase 赋值。
    """
    model_config = ConfigDict(populate_by_name=True, from_attributes=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _normalize_payload_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                continue
            snake_key = _camel_to_snake(raw_key)
            if snake_key and snake_key not in normalized:
                normalized[snake_key] = raw_value
        return normalized
