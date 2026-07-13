#!/usr/bin/env python3
"""Клиент Bitrix24 REST API (через входящий webhook) для статистики по заявкам."""
import os
import collections
import logging

import requests

logger = logging.getLogger(__name__)

BITRIX24_WEBHOOK_URL = os.environ.get("BITRIX24_WEBHOOK_URL", "").rstrip("/")

REQUEST_TIMEOUT = 30
PAGE_SIZE = 50


def _call(method: str, params: dict) -> dict:
    if not BITRIX24_WEBHOOK_URL:
        raise RuntimeError("BITRIX24_WEBHOOK_URL не задан")
    url = f"{BITRIX24_WEBHOOK_URL}/{method}.json"
    resp = requests.post(url, json=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Bitrix24 API error [{data['error']}]: {data.get('error_description', '')}")
    return data


def _list_all(method: str, filter_params: dict, select: list) -> list:
    items = []
    start = 0
    while True:
        data = _call(method, {
            "filter": filter_params,
            "select": select,
            "start": start,
            "order": {"ID": "ASC"},
        })
        items.extend(data.get("result", []))
        next_start = data.get("next")
        if next_start is None:
            break
        start = next_start
    return items


def get_leads(date_from: str, date_to: str) -> list:
    """Заявки-лиды (crm.lead), созданные в диапазоне [date_from, date_to] (YYYY-MM-DD)."""
    filter_params = {">=DATE_CREATE": date_from, "<=DATE_CREATE": f"{date_to}T23:59:59"}
    select = ["ID", "DATE_CREATE", "STATUS_ID", "SOURCE_ID", "TITLE"]
    return _list_all("crm.lead.list", filter_params, select)


def get_deals(date_from: str, date_to: str) -> list:
    """Сделки (crm.deal), созданные в диапазоне [date_from, date_to] (YYYY-MM-DD)."""
    filter_params = {">=DATE_CREATE": date_from, "<=DATE_CREATE": f"{date_to}T23:59:59"}
    select = ["ID", "DATE_CREATE", "STAGE_ID", "SOURCE_ID", "TITLE"]
    return _list_all("crm.deal.list", filter_params, select)


def _status_field(entity_kind: str) -> str:
    return "STAGE_ID" if entity_kind == "deals" else "STATUS_ID"


def build_report(entity_kind: str, items: list, month_ranges: list) -> str:
    """month_ranges: список (label, date_from, date_to) для разбивки по месяцам."""
    status_field = _status_field(entity_kind)
    label_ru = "Сделки" if entity_kind == "deals" else "Лиды (заявки)"

    lines = [f"Статистика по Bitrix24 — {label_ru}", ""]

    by_month = collections.OrderedDict((label, []) for label, _, _ in month_ranges)
    for item in items:
        created = item.get("DATE_CREATE", "")[:10]
        for label, date_from, date_to in month_ranges:
            if date_from <= created <= date_to:
                by_month[label].append(item)
                break

    total = 0
    for label, month_items in by_month.items():
        total += len(month_items)
        lines.append(f"{label}: {len(month_items)}")

        by_status = collections.Counter(i.get(status_field) or "не указан" for i in month_items)
        by_source = collections.Counter(i.get("SOURCE_ID") or "не указан" for i in month_items)

        if month_items:
            lines.append("  по статусам:")
            for status, count in by_status.most_common():
                lines.append(f"    {status}: {count}")
            lines.append("  по источникам:")
            for source, count in by_source.most_common():
                lines.append(f"    {source}: {count}")
        lines.append("")

    lines.append(f"Всего за период: {total}")
    return "\n".join(lines)
