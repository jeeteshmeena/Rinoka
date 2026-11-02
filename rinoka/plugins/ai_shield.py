"""Rinoka AI Shield.

Watches every message in the group and removes porn / sexual content, scam
offers, phishing and malware links on its own, with no filters to set up.
It reads text, captions, links (including hidden behind shorteners and inline
buttons), photos, stickers, GIF and video thumbnails, and the names and bios of
people who join.
"""

import asyncio
import html
import time
from typing import Any, ClassVar, Dict, List, MutableMapping, Optional, Tuple

from pyrogram.enums import MessageEntityType
from pyrogram.errors import (
    ChatAdminRequired,
    MessageDeleteForbidden,
    PeerIdInvalid,
    UserAdminInvalid,
    UserNotParticipant,
)
from pyrogram.types import CallbackQuery, ChatPermissions, Message, User

from rinoka import command, filters, listener, plugin, util
from rinoka.util.ai_guard import AIGuard, Verdict, extract_urls, score_text
from rinoka.util.botapi import btn
from rinoka.util.misc import StopPropagation

SENSITIVITY = {"low": 0.85, "medium": 0.6, "high": 0.4}
IMAGE_THRESHOLD = {"low": 0.7, "medium": 0.55, "high": 0.4}
ACTIONS = ("ban", "mute", "warn", "delete")
LABEL = {
    "sexual": "🔞 Sexual content",
    "csam": "⛔ Child abuse content",
    "scam": "💸 Scam",
    "phishing": "🎣 Phishing link",
    "malware": "🦠 Malware link/file",
    "hate": "🤬 Hate/abuse",
    "spam": "📢 Spam",
}
MAX_IMAGE = 6 * 1024 * 1024
NEW_USER_SECONDS = 3 * 24 * 3600


class AIShield(plugin.Plugin):
    name: ClassVar[str] = "AI Shield"
    helpable: ClassVar[bool] = True

    db: util.db.AsyncCollection
    media_db: util.db.AsyncCollection
    seen_db: util.db.AsyncCollection
    guard: AIGuard
    _admins: Dict[int, Tuple[float, set]]
    _name_checked: Dict[Tuple[int, int], float]

    async def on_load(self) -> None:
        cfg = self.bot.config
        self.db = self.bot.db.get_collection("AI_SHIELD")
        self.media_db = self.bot.db.get_collection("AI_SHIELD_MEDIA")
        self.seen_db = self.bot.db.get_collection("AI_SHIELD_SEEN")
        self.guard = AIGuard(
            self.bot.http,
            gemini_key=cfg.GEMINI_API_KEY,
            gemini_model=cfg.GEMINI_MODEL,
            safe_browsing_key=cfg.SAFE_BROWSING_KEY,
            local_model=cfg.NSFW_LOCAL_MODEL,
        )
        self._admins = {}
        self._name_checked = {}
        if not cfg.GEMINI_API_KEY:
            self.log.warning("GEMINI_API_KEY not set: AI Shield runs on local rules + NudeNet only")

    async def on_start(self, _: int) -> None:
        # warm up the vision model so the first photo is not slow
        self.bot.loop.create_task(self.guard._load_detector())

    async def on_chat_migrate(self, message: Message) -> None:
        await self.db.update_one(
            {"chat_id": message.migrate_from_chat_id}, {"$set": {"chat_id": message.chat.id}}
        )

    async def on_plugin_backup(self, chat_id: int) -> MutableMapping[str, Any]:
        data = await self.db.find_one({"chat_id": chat_id}, {"_id": False})
        return {self.name: data} if data else {}

    async def on_plugin_restore(self, chat_id: int, data: MutableMapping[str, Any]) -> None:
        await self.db.update_one({"chat_id": chat_id}, {"$set": data[self.name]}, upsert=True)

    # { settings / helpers
    async def settings(self, chat_id: int) -> Dict[str, Any]:
        data = await self.db.find_one({"chat_id": chat_id}) or {}
        return {
            "enabled": data.get("enabled", True),
            "action": data.get("action", "ban"),
            "level": data.get("level", "medium"),
            "allow": data.get("allow", []),
            "warn_limit": int(data.get("warn_limit", 3)),
        }

    async def admin_ids(self, chat_id: int) -> set:
        cached = self._admins.get(chat_id)
        if cached and cached[0] > time.time():
            return cached[1]
        ids = set()
        try:
            async for m in util.tg.get_chat_admins(self.bot.client, chat_id):
                ids.add(m.user.id)
        except (ChatAdminRequired, PeerIdInvalid):
            pass
        self._admins[chat_id] = (time.time() + 600, ids)
        return ids

    async def is_exempt(self, chat_id: int, user: Optional[User]) -> bool:
        if not user:
            return False
        return user.id == self.bot.uid or util.tg.is_staff(user.id) or user.id in await self.admin_ids(chat_id)

    async def is_new_user(self, chat_id: int, user_id: int) -> bool:
        doc = await self.seen_db.find_one_and_update(
            {"chat_id": chat_id, "user_id": user_id},
            {"$setOnInsert": {"first": time.time()}, "$inc": {"count": 1}},
            upsert=True,
            return_document=True,
        )
        return bool(doc) and (doc.get("count", 0) <= 20 or time.time() - doc.get("first", 0) < NEW_USER_SECONDS)

    @staticmethod
    def _message_text(message: Message) -> str:
        parts = [message.text or "", message.caption or ""]
        if message.poll:
            parts.append(message.poll.question or "")
            parts.extend(o.text for o in message.poll.options or [])
        if message.reply_markup and getattr(message.reply_markup, "inline_keyboard", None):
            for row in message.reply_markup.inline_keyboard:
                parts.extend(b.text or "" for b in row)
        return "\n".join(p for p in parts if p).strip()

    @staticmethod
    def _entity_urls(message: Message) -> List[str]:
        urls: List[str] = []
        for ent in (message.entities or []) + (message.caption_entities or []):
            if ent.type == MessageEntityType.TEXT_LINK and ent.url:
                urls.append(ent.url)
        if message.reply_markup and getattr(message.reply_markup, "inline_keyboard", None):
            for row in message.reply_markup.inline_keyboard:
                urls.extend(b.url for b in row if getattr(b, "url", None))
        if message.web_page and message.web_page.url:
            urls.append(message.web_page.url)
        return urls

    def _media_target(self, message: Message) -> Optional[Tuple[str, str, str, int]]:
        """(file_id_to_download, unique_id, mime, size) for the image we should scan."""
        if message.photo:
            p = message.photo
            return p.file_id, p.file_unique_id, "image/jpeg", p.file_size or 0
        if message.sticker:
            s = message.sticker
            if s.is_animated or s.is_video:
                if s.thumbs:
                    return s.thumbs[0].file_id, s.file_unique_id, "image/webp", s.thumbs[0].file_size or 0
                return None
            return s.file_id, s.file_unique_id, "image/webp", s.file_size or 0
        for media in (message.animation, message.video, message.video_note):
            if media and media.thumbs:
                t = media.thumbs[-1]
                return t.file_id, media.file_unique_id, "image/jpeg", t.file_size or 0
        doc = message.document
        if doc and (doc.mime_type or "").startswith("image/") and (doc.file_size or 0) <= MAX_IMAGE:
            return doc.file_id, doc.file_unique_id, doc.mime_type or "image/jpeg", doc.file_size or 0
        return None

    # }

    # { core check
    async def analyse(self, message: Message, conf: Dict[str, Any], *, new_user: bool) -> Verdict:
        level = conf["level"]
        text = self._message_text(message)
        verdict = Verdict()

        # 1. known-bad media / sticker packs (instant, no download)
        target = self._media_target(message)
        if target:
            known = await self.media_db.find_one({"_id": target[1]})
            if known and known.get("category"):
                return Verdict(known["category"], 1.0, ["previously flagged media"], "memory")
        if message.sticker and message.sticker.set_name:
            known_set = await self.media_db.find_one({"_id": f"set:{message.sticker.set_name}"})
            if known_set and known_set.get("hits", 0) >= 2:
                return Verdict("sexual", 0.95, [f"sticker pack {message.sticker.set_name} is flagged"], "memory")

        # 2. sender name (fake 'hot girl' accounts)
        user = message.from_user
        if user:
            name = " ".join(filter(None, [user.first_name, user.last_name, user.username]))
            name_v = score_text(name)
            if name_v.score >= 0.75:
                verdict = verdict.merge(Verdict(name_v.category, name_v.score, [f"name: {name_v.reasons[0]}"], "rules"))

        # 3. links
        urls = extract_urls(text, self._entity_urls(message))
        if urls:
            verdict = verdict.merge(await self.guard.check_links(urls, conf["allow"]))

        # 4. text / caption with the AI brain
        if text:
            verdict = verdict.merge(
                await self.guard.check_text(
                    text, sensitivity=SENSITIVITY[level], use_ai=True, force_ai=new_user
                )
            )

        # 5. image / sticker / video thumbnail
        if target and not verdict.severe and (target[3] or 0) <= MAX_IMAGE:
            try:
                blob = await self.bot.client.download_media(target[0], in_memory=True)
                data = bytes(blob.getbuffer()) if blob else b""
            except Exception as err:  # skipcq: PYL-W0703
                self.log.debug("download failed: %s", err)
                data = b""
            if data:
                img_v = await self.guard.check_image(
                    data, unique_id=target[1], threshold=IMAGE_THRESHOLD[level], mime=target[2]
                )
                verdict = verdict.merge(img_v)
                if img_v.flagged:
                    await self.media_db.update_one(
                        {"_id": target[1]}, {"$set": {"category": img_v.category, "at": time.time()}}, upsert=True
                    )
                    if message.sticker and message.sticker.set_name:
                        await self.media_db.update_one(
                            {"_id": f"set:{message.sticker.set_name}"}, {"$inc": {"hits": 1}}, upsert=True
                        )

        if verdict.flagged and verdict.score < SENSITIVITY[level] and verdict.category not in {"csam"}:
            return Verdict()
        return verdict

    @listener.priority(50)
    @listener.filters(filters.group & ~filters.outgoing & ~filters.service)
    async def on_message(self, message: Message) -> None:
        chat = message.chat
        user = message.from_user
        if not user and not message.sender_chat:
            return
        conf = await self.settings(chat.id)
        if not conf["enabled"] or await self.is_exempt(chat.id, user):
            return
        if message.sender_chat and message.sender_chat.id == chat.id:
            return  # anonymous admin

        new_user = await self.is_new_user(chat.id, user.id) if user else True
        verdict = await self.analyse(message, conf, new_user=new_user)
        if not verdict.flagged:
            return

        await self.enforce(message, verdict, conf)
        raise StopPropagation

    @listener.priority(45)
    async def on_chat_action(self, message: Message) -> None:
        """Check the names and bios of people who join."""
        if not message.new_chat_members:
            return
        chat = message.chat
        conf = await self.settings(chat.id)
        if not conf["enabled"]:
            return
        for member in message.new_chat_members:
            if member.is_bot or await self.is_exempt(chat.id, member):
                continue
            key = (chat.id, member.id)
            if self._name_checked.get(key, 0) > time.time():
                continue
            self._name_checked[key] = time.time() + 3600
            profile = " ".join(filter(None, [member.first_name, member.last_name, member.username]))
            try:
                full = await self.bot.client.get_chat(member.id)
                profile += "\n" + (getattr(full, "bio", "") or "")
            except Exception:  # skipcq: PYL-W0703
                pass
            verdict = await self.guard.check_text(profile, sensitivity=0.75, use_ai=True)
            if verdict.flagged and verdict.score >= 0.75:
                verdict.reasons.insert(0, "profile name/bio")
                await self.enforce(message, verdict, {**conf, "action": "ban"}, target=member, delete=False)

    # }

    # { enforcement
    async def enforce(
        self,
        message: Message,
        verdict: Verdict,
        conf: Dict[str, Any],
        *,
        target: Optional[User] = None,
        delete: bool = True,
    ) -> None:
        chat = message.chat
        user = target or message.from_user
        if delete:
            try:
                await message.delete()
            except MessageDeleteForbidden:
                self.log.info("No delete rights in %s", chat.id)

        action = conf["action"]
        if verdict.category in {"csam", "malware", "phishing"} or (verdict.category == "sexual" and verdict.source in {"vision", "memory", "links"}):
            action = "ban" if action != "delete" else "delete"
        done = "deleted"
        if user:
            try:
                if action == "ban":
                    await self.bot.client.ban_chat_member(chat.id, user.id)
                    done = "banned"
                elif action == "mute":
                    await self.bot.client.restrict_chat_member(chat.id, user.id, ChatPermissions())
                    done = "muted"
                elif action == "warn":
                    doc = await self.seen_db.find_one_and_update(
                        {"chat_id": chat.id, "user_id": user.id},
                        {"$inc": {"strikes": 1}},
                        upsert=True,
                        return_document=True,
                    )
                    strikes = (doc or {}).get("strikes", 1)
                    if strikes >= conf["warn_limit"]:
                        await self.bot.client.ban_chat_member(chat.id, user.id)
                        done = f"banned after {strikes} warnings"
                    else:
                        done = f"warned ({strikes}/{conf['warn_limit']})"
            except (ChatAdminRequired, UserAdminInvalid, UserNotParticipant, PeerIdInvalid) as err:
                self.log.info("Action %s failed in %s: %s", action, chat.id, err)

        who = (
            f'<a href="tg://user?id={user.id}">{html.escape(user.first_name or "User")}</a>' if user else "A channel"
        )
        reason = html.escape("; ".join(verdict.reasons[:2]) or verdict.category)
        text = (
            f"🛡 <b>Rinoka AI Shield</b>\n"
            f"{LABEL.get(verdict.category, verdict.category)} removed. {who} was <b>{done}</b>.\n"
            f"<blockquote expandable>Why: {reason}\nConfidence: {int(verdict.score * 100)}% · {verdict.source}</blockquote>"
        )
        keyboard = None
        if user and done != "deleted":
            keyboard = [[
                btn("↩️ Undo", f"ais_undo_{user.id}", style="success"),
                btn("✔️ OK", "ais_ok", style="primary"),
            ]]
        sent = await self.bot.botapi.send_message(
            chat.id, text, keyboard=keyboard, thread_id=message.message_thread_id if message.is_topic_message else None
        )
        if sent:
            self.bot.loop.create_task(self._auto_delete(chat.id, sent["message_id"], 120))

        await self.bot.dispatch_event(
            "ai_shield_action", chat.id, user.id if user else None, verdict.category, done
        )

    async def _auto_delete(self, chat_id: int, msg_id: int, delay: int) -> None:
        await asyncio.sleep(delay)
        await self.bot.botapi.delete(chat_id, [msg_id])

    @listener.filters(filters.regex(r"^ais_(undo|ok)(?:_(\d+))?$"))
    async def on_callback_query(self, query: CallbackQuery) -> None:
        chat = query.message.chat
        if query.from_user.id not in await self.admin_ids(chat.id) and not util.tg.is_staff(query.from_user.id):
            await query.answer("Only admins can use this.", show_alert=True)
            return
        action, user_id = query.matches[0].group(1), query.matches[0].group(2)
        if action == "undo" and user_id:
            try:
                await self.bot.client.unban_chat_member(chat.id, int(user_id))
                await self.seen_db.update_one({"chat_id": chat.id, "user_id": int(user_id)}, {"$set": {"strikes": 0}})
            except (ChatAdminRequired, PeerIdInvalid):
                pass
            await query.answer("Action undone. They can join/chat again.")
        else:
            await query.answer("👍")
        try:
            await query.message.delete()
        except MessageDeleteForbidden:
            pass

    # }

    # { commands
    @command.filters(filters.admin_only)
    async def cmd_aishield(self, ctx: command.Context) -> str:
        arg = (ctx.input or "").strip().lower()
        if arg in {"on", "off"}:
            await self.db.update_one({"chat_id": ctx.chat.id}, {"$set": {"enabled": arg == "on"}}, upsert=True)
            return f"🛡 AI Shield is **{arg}**."
        conf = await self.settings(ctx.chat.id)
        brain = "Gemini AI + " if self.bot.config.GEMINI_API_KEY else ""
        links = "Safe Browsing + " if self.bot.config.SAFE_BROWSING_KEY else ""
        vision = "NudeNet" if await self.guard._load_detector() else "no local vision model"
        return (
            f"🛡 **AI Shield**: {'on' if conf['enabled'] else 'off'}\n"
            f"Action: **{conf['action']}** · Sensitivity: **{conf['level']}** · Warn limit: {conf['warn_limit']}\n"
            f"Engines: {brain}{links}rules + {vision}\n"
            f"Allowed domains: {', '.join(conf['allow']) or 'none'}"
        )

    @command.filters(filters.admin_only)
    async def cmd_aiaction(self, ctx: command.Context) -> str:
        arg = (ctx.input or "").strip().lower()
        if arg not in ACTIONS:
            return "Usage: `/aiaction ban|mute|warn|delete`"
        await self.db.update_one({"chat_id": ctx.chat.id}, {"$set": {"action": arg}}, upsert=True)
        return f"AI Shield will now **{arg}** offenders. Porn media, phishing and malware always get a ban unless set to delete."

    @command.filters(filters.admin_only)
    async def cmd_aisens(self, ctx: command.Context) -> str:
        arg = (ctx.input or "").strip().lower()
        if arg not in SENSITIVITY:
            return "Usage: `/aisens low|medium|high`"
        await self.db.update_one({"chat_id": ctx.chat.id}, {"$set": {"level": arg}}, upsert=True)
        return f"AI Shield sensitivity set to **{arg}**."

    @command.filters(filters.admin_only)
    async def cmd_aiallow(self, ctx: command.Context) -> str:
        domain = (ctx.input or "").strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
        if not domain:
            return "Usage: `/aiallow example.com` (use `/aiallow -example.com` to remove)"
        if domain.startswith("-"):
            await self.db.update_one({"chat_id": ctx.chat.id}, {"$pull": {"allow": domain[1:]}}, upsert=True)
            return f"Removed **{domain[1:]}** from allowed domains."
        await self.db.update_one({"chat_id": ctx.chat.id}, {"$addToSet": {"allow": domain}}, upsert=True)
        return f"Links to **{domain}** will no longer be flagged."

    @command.filters(filters.admin_only)
    async def cmd_aiscan(self, ctx: command.Context) -> str:
        """Reply to a message to see what AI Shield thinks of it, without acting."""
        reply = ctx.msg.reply_to_message
        if not reply:
            return "Reply to a message with `/aiscan`."
        conf = await self.settings(ctx.chat.id)
        verdict = await self.analyse(reply, conf, new_user=True)
        if not verdict.flagged:
            return "✅ Looks safe."
        return (
            f"{LABEL.get(verdict.category, verdict.category)} · {int(verdict.score * 100)}% via {verdict.source}\n"
            + "\n".join(f"• {r}" for r in verdict.reasons[:4])
        )

    # }
