"""Send alerts over WhatsApp (Meta WhatsApp Cloud API), or print them (dry run).

Set environment variables to go live:
    WHATSAPP_TOKEN            permanent access token from Meta for Developers
    WHATSAPP_PHONE_NUMBER_ID  the sender phone-number ID
    WHATSAPP_API_VERSION      optional, e.g. v21.0

WhatsApp only allows free-form text within 24 h of the farmer last messaging
you. For scheduled alerts outside that window, register an approved *template*
message in Meta Business Manager and send it with `send_template`. Asking each
farmer to reply "OK" to the daily alert keeps the 24-hour window open.
"""
from __future__ import annotations

import os

import requests


class Notifier:
    def send(self, to: str, text: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleNotifier(Notifier):
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, to: str, text: str) -> bool:
        self.sent.append((to, text))
        print(f"[dry-run WhatsApp -> {to}] {text}")
        return True


class WhatsAppNotifier(Notifier):
    def __init__(self, token: str, phone_number_id: str, api_version: str = "v21.0"):
        self.url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def send(self, to: str, text: str) -> bool:
        body = {"messaging_product": "whatsapp", "to": to, "type": "text",
                "text": {"preview_url": False, "body": text}}
        try:
            r = requests.post(self.url, json=body, headers=self.headers, timeout=10)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def send_template(self, to: str, template: str, language: str, params: list[str]) -> bool:
        body = {"messaging_product": "whatsapp", "to": to, "type": "template",
                "template": {"name": template, "language": {"code": language},
                             "components": [{"type": "body", "parameters":
                                             [{"type": "text", "text": p} for p in params]}]}}
        try:
            r = requests.post(self.url, json=body, headers=self.headers, timeout=10)
            return r.status_code == 200
        except requests.RequestException:
            return False


def notifier_from_env() -> Notifier:
    token, pid = os.environ.get("WHATSAPP_TOKEN"), os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    if token and pid:
        return WhatsAppNotifier(token, pid, os.environ.get("WHATSAPP_API_VERSION", "v21.0"))
    return ConsoleNotifier()
