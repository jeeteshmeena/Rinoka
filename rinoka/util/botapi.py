"""Thin HTTP Bot API helper for Rinoka.

Pyrofork (MTProto) does not expose the newest Telegram UI features yet, so Rinoka
sends a few UI-heavy messages through the official HTTP Bot API instead:

* coloured inline buttons (``style``: primary / success / danger, Bot API 9.4)
* Rich Messages with headings, lists, quotes and inline buttons (Bot API 10.1+)
* ephemeral messages that only one user can see (Bot API 10.3)

Every helper falls back to a plain HTML message when the feature is not
available, so the bot keeps working even if Telegram rejects a field.
Callback queries from these buttons still arrive through the normal MTProto
update stream, so plugins handle them with ``on_callback_query`` as usual.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Sequence

import aiohttp

log = logging.getLogger("botapi")

Button = Dict[str, Any]
Keyboard = List[List[Button]]

_TAG_RE = re.compile(r"<(?!/?(b|strong|i|em|u|ins|s|strike|del|a|code|pre|blockquote|tg-spoiler)\b)[^>]*>")


def btn(
    text: str,
    data: Optional[str] = None,
    *,
    url: Optional[str] = None,
    style: Optional[str] = None,
    emoji_id: Optional[str] = None,
) -> Button:
    """Build one inline button. ``style`` is "primary", "success" or "danger"."""
    button: Button = {"text": text}
    if url:
        button["url"] = url
    else:
        button["callback_data"] = data or "noop"
    if style:
        button["style"] = style
    if emoji_id:
        button["icon_custom_emoji_id"] = emoji_id
    return button


def _strip_style(keyboard: Optional[Keyboard]) -> Optional[Keyboard]:
    if not keyboard:
        return keyboard
    return [
        [{k: v for k, v in b.items() if k not in {"style", "icon_custom_emoji_id"}} for b in row]
        for row in keyboard
    ]


def html_fallback(rich_html: str) -> str:
    """Turn rich-message HTML into regular Telegram HTML."""
    text = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r"<b>\1</b>\n", rich_html, flags=re.S)
    text = re.sub(r"<li[^>]*>", "• ", text)
    text = re.sub(r"</li>|</p>|<br\s*/?>", "\n", text)
    text = re.sub(r"<hr\s*/?>", "\n──────────\n", text)
    text = _TAG_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class BotAPI:
    def __init__(self, http: aiohttp.ClientSession, token: str) -> None:
        self.http = http
        self.base = f"https://api.telegram.org/bot{token}/"
        self.rich_supported = True

    async def call(self, method: str, **params: Any) -> Any:
        payload = {k: v for k, v in params.items() if v is not None}
        async with self.http.post(self.base + method, json=payload) as resp:
            data = await resp.json(content_type=None)
        if not data.get("ok"):
            raise BotAPIError(method, data.get("description", "unknown error"))
        return data.get("result")

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        keyboard: Optional[Keyboard] = None,
        reply_to: Optional[int] = None,
        thread_id: Optional[int] = None,
        ephemeral_for: Optional[int] = None,
        protect: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """HTML message with coloured buttons; retries without new fields on error."""
        base: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "message_thread_id": thread_id,
            "protect_content": protect or None,
        }
        if reply_to:
            base["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}

        attempts = []
        extra: Dict[str, Any] = {}
        if keyboard:
            extra["reply_markup"] = {"inline_keyboard": keyboard}
        if ephemeral_for:
            attempts.append({**extra, "ephemeral_message_parameters": {"receiver_user_id": ephemeral_for}})
        attempts.append(extra)
        if keyboard:
            attempts.append({"reply_markup": {"inline_keyboard": _strip_style(keyboard)}})

        last_err: Optional[Exception] = None
        for attempt in attempts:
            try:
                return await self.call("sendMessage", **base, **attempt)
            except BotAPIError as err:
                last_err = err
                log.debug("sendMessage fallback after: %s", err)
        log.warning("sendMessage failed in %s: %s", chat_id, last_err)
        return None

    async def send_rich(
        self,
        chat_id: int,
        rich_html: str,
        *,
        keyboard: Optional[Keyboard] = None,
        reply_to: Optional[int] = None,
        thread_id: Optional[int] = None,
        ephemeral_for: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Send a Rich Message (headings, lists, quotes); falls back to plain HTML."""
        if self.rich_supported:
            params: Dict[str, Any] = {
                "chat_id": chat_id,
                "rich_message": {"html": rich_html},
                "message_thread_id": thread_id,
            }
            if keyboard:
                params["reply_markup"] = {"inline_keyboard": keyboard}
            if reply_to:
                params["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
            if ephemeral_for:
                params["ephemeral_message_parameters"] = {"receiver_user_id": ephemeral_for}
            try:
                return await self.call("sendRichMessage", **params)
            except BotAPIError as err:
                if "not found" in str(err).lower():
                    self.rich_supported = False
                log.debug("sendRichMessage fallback after: %s", err)

        return await self.send_message(
            chat_id,
            html_fallback(rich_html),
            keyboard=keyboard,
            reply_to=reply_to,
            thread_id=thread_id,
            ephemeral_for=ephemeral_for,
        )

    async def edit_text(
        self, chat_id: int, message_id: int, text: str, keyboard: Optional[Keyboard] = None
    ) -> None:
        markup = {"inline_keyboard": keyboard} if keyboard else None
        for kb in (markup, {"inline_keyboard": _strip_style(keyboard)} if keyboard else None):
            try:
                await self.call(
                    "editMessageText",
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                    link_preview_options={"is_disabled": True},
                )
                return
            except BotAPIError as err:
                if "not modified" in str(err).lower():
                    return
                log.debug("editMessageText fallback after: %s", err)

    async def delete(self, chat_id: int, message_ids: Sequence[int]) -> None:
        try:
            await self.call("deleteMessages", chat_id=chat_id, message_ids=list(message_ids))
        except BotAPIError as err:
            log.debug("deleteMessages failed: %s", err)


class BotAPIError(Exception):
    def __init__(self, method: str, description: str) -> None:
        super().__init__(f"{method}: {description}")
        self.method = method
        self.description = description
