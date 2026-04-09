# -*- coding: utf-8 -*-
"""
来财 (Attract-wealth) — 统一 Pydantic Schema 契约
解决 snake_case (后端) 与 camelCase (前端) 的自动转换问题。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BaseSchema(BaseModel):
    """
    基础 Schema 类。
    - 自动将 snake_case 字段映射为 camelCase 供前端使用。
    - 允许通过 snake_case 或 camelCase 赋值。
    """
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
