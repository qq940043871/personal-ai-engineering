"""步骤类型注册表：DSL 与代码的唯一接缝。

- YAML 里的 type 必须在注册表里能找到；启动时全量校验（配置错误启动期爆）。
- 步骤统一接口 run(ctx, params) -> StepResult：失败也是结果，不是异常
  （同构 Harness 报文铁律第 4 条：工具失败也回一条结果）。
"""
from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # 避免循环导入
    from ownrag.core.pipeline import StepContext

STEP_REGISTRY: dict[str, type["Step"]] = {}


def register(name: str) -> Callable:
    def deco(cls: type["Step"]) -> type["Step"]:
        if name in STEP_REGISTRY:
            raise ValueError(f"步骤类型重复注册：{name}")
        STEP_REGISTRY[name] = cls
        return cls
    return deco


@dataclass
class StepResult:
    """status: ok | fail。fail 必须带 error（给 trace 与待办表看）。"""
    status: str
    data: dict = field(default_factory=dict)      # 并入 ctx.data 的增量
    metrics: dict = field(default_factory=dict)   # 计数（页数/块数/行数…）进 trace
    error: str | None = None

    @classmethod
    def ok(cls, data: dict | None = None, **metrics: Any) -> "StepResult":
        return cls("ok", data or {}, metrics)

    @classmethod
    def fail(cls, error: str, **metrics: Any) -> "StepResult":
        return cls("fail", {}, metrics, error)


class Step(ABC):
    """所有步骤类型继承此类；实现必须无状态——中间数据只走 ctx。"""

    @abstractmethod
    def run(self, ctx: "StepContext", params: dict) -> StepResult: ...


def validate_pipeline_steps(pipelines: dict) -> list[str]:
    """启动期校验：返回缺失步骤类型清单（空 = 通过）。"""
    missing: set[str] = set()
    for pipe_name, spec in pipelines.items():
        for step_spec in spec.get("steps", []):
            missing |= _check_one(pipe_name, step_spec)
            for fb in step_spec.get("fallback", []) or []:
                missing |= _check_one(f"{pipe_name}(fallback)", fb)
    return sorted(missing)


def _check_one(pipe_name: str, step_spec: dict) -> set[str]:
    t = step_spec.get("type")
    cls = STEP_REGISTRY.get(t)
    if cls is None:
        return {f"{pipe_name}: 步骤类型未注册 -> {t!r}"}
    if not (inspect.isclass(cls) and issubclass(cls, Step)):
        return {f"{pipe_name}: {t!r} 不是 Step 子类"}
    return set()
