"""Failure kinds shared by the library, CLI, and local API."""

from __future__ import annotations

from typing import Any

# Kinds a human may retry after looking at the screen or waiting.
RETRYABLE_KINDS = frozenset({"transient", "rate_limited", "verify_unconfirmed"})

# The set did not land, and another automatic write would add risk.
STOP_KINDS = frozenset({"rollback_failed", "verify_unconfirmed", "policy_blocked"})

MESSAGES: dict[str, str] = {
    "confirm_required": "未确认，已拒绝写入。",
    "rate_limited": "写入过于频繁，已拒绝。",
    "value_out_of_range": "亮度必须是 0 到 100 的整数，且不能超过显示器报告的最大值。",
    "platform_unsupported": "当前系统不是 Windows，或 dxva2 不可用。没有写入。",
    "unknown_monitor": "没有这块显示器。请重新探测后再试。",
    "identity_ambiguous": "有两台显示器分不开（缺少序列号且特征相同）。为避免写错屏幕，已拒绝。",
    "identity_unstable": "没有可靠的 EDID 或型号身份，已拒绝写入。",
    "internal_panel": "这像是笔记本内置屏。内屏不走 DDC，本工具不会写它。",
    "ddc_off": "EDID 在，但读不到 VCP 0x10。优先检查 OSD 里的 DDC/CI；刚换过线或扩展坞时也要一起看。",
    "cable": "没有 EDID，也没有 VCP。优先检查线材、扩展坞、休眠和当前输入源。",
    "transient": "这次读取超时或忙。没有写入。",
    "unsupported": "能力字符串里没有亮度码，或亮度不可读。已拒绝写入。",
    "unsupported_scale": "VCP 0x10 的最大值不是 100，刻度无法确认，已拒绝写入。",
    "probe_failed": "探测失败，已拒绝写入。",
    "policy_blocked": "该 VCP 码不在允许列表。目前只允许亮度 0x10。",
    "write_failed": "亮度写入被系统拒绝。没有再补一次写入。",
    "verify_mismatch": "回读和目标不一致，已写回探测时的亮度。",
    "verify_unconfirmed": "写入指令已发出，但没能读回亮度。没有做第二次写入。请先看画面。",
    "rollback_failed": "回读和目标不一致，写回原亮度也失败。请到显示器菜单确认当前亮度，不要连续重试。",
}

_WINERR_KINDS = frozenset(
    {
        "ddc_off",
        "cable",
        "transient",
        "probe_failed",
        "internal_panel",
        "unsupported",
        "write_failed",
    }
)


def message_for(kind: str, winerr: int | None = None) -> str:
    text = MESSAGES.get(kind, kind)
    if winerr is not None and kind in _WINERR_KINDS:
        return f"{text}（winerr {winerr}）"
    return text


class DisplayError(Exception):
    """A refused or unfinished brightness operation. Never implies 'try the write again blindly'."""

    def __init__(self, kind: str, message: str | None = None, **details: Any) -> None:
        self.kind = kind
        self.message = message if message is not None else message_for(kind)
        self.details = details
        super().__init__(f"{kind}: {self.message}")

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_KINDS

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "kind": self.kind,
            "message": self.message,
            "retryable": self.retryable,
        }
        for key, value in self.details.items():
            if value is not None:
                body[key] = value
        return body
