"""Rinoka Terms & Conditions gate.

A member can only take part in the group after reading and accepting the
group's Terms & Conditions.

Two flows are covered:

1. Join requests (recommended): turn on "Approve new members" in the group
   (or use an invite link with admin approval). Rinoka DMs the requester the
   T&C with an "I Agree" button and approves the request only after they agree.
   If they decline or do nothing until the timeout, the request is declined.

2. Direct joins (public group or plain invite link): Rinoka mutes the new member
   and posts the T&C with an "I Agree" button that only that member can press.
   Agreeing unmutes them; ignoring it until the timeout removes them.
"""

import asyncio
import html
import time
from typing import Any, ClassVar, MutableMapping, Optional

from pyrogram.errors import (
    ChatAdminRequired,
    HideRequesterMissing,
    MessageDeleteForbidden,
    PeerIdInvalid,
    UserAlreadyParticipant,
    UserIsBlocked,
    UserNotParticipant,
)
from pyrogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from rinoka import command, filters, listener, plugin, util
from rinoka.util.botapi import btn

DEFAULT_TNC = (
    "1. No porn, nudity or sexual content of any kind (text, photo, sticker, video, link).\n"
    "2. No scam, phishing, malware, APK or suspicious links.\n"
    "3. No spam, promotion or unsolicited DMs to members.\n"
    "4. Respect everyone. No abuse, hate or harassment.\n"
    "5. Admins' decisions are final. Breaking these rules gets you banned automatically.\n\n"
    "Hindi: Porn/sexual content, scam ya malware links, spam aur gaali-galoch par seedha ban hoga."
)
DEFAULT_TIMEOUT_MIN = 5


class TncGate(plugin.Plugin):
    name: ClassVar[str] = "TnC Gate"
    helpable: ClassVar[bool] = True

    db: util.db.AsyncCollection
    pending_db: util.db.AsyncCollection
    accepted_db: util.db.AsyncCollection
    _sweeper: Optional[asyncio.Task]

    async def on_load(self) -> None:
        self.db = self.bot.db.get_collection("TNC_GATE")
        self.pending_db = self.bot.db.get_collection("TNC_PENDING")
        self.accepted_db = self.bot.db.get_collection("TNC_ACCEPTED")
        self._sweeper = None

    async def on_start(self, _: int) -> None:
        self._sweeper = self.bot.loop.create_task(self._sweep_loop())

    async def on_stop(self) -> None:
        if self._sweeper:
            self._sweeper.cancel()

    async def on_chat_migrate(self, message: Message) -> None:
        old, new = message.migrate_from_chat_id, message.chat.id
        for col in (self.db, self.pending_db, self.accepted_db):
            await col.update_many({"chat_id": old}, {"$set": {"chat_id": new}})

    async def on_plugin_backup(self, chat_id: int) -> MutableMapping[str, Any]:
        data = await self.db.find_one({"chat_id": chat_id}, {"_id": False})
        return {self.name: data} if data else {}

    async def on_plugin_restore(self, chat_id: int, data: MutableMapping[str, Any]) -> None:
        await self.db.update_one({"chat_id": chat_id}, {"$set": data[self.name]}, upsert=True)

    # { settings
    async def settings(self, chat_id: int) -> MutableMapping[str, Any]:
        data = await self.db.find_one({"chat_id": chat_id}) or {}
        return {
            "enabled": data.get("enabled", False),
            "text": data.get("text") or DEFAULT_TNC,
            "timeout": int(data.get("timeout", DEFAULT_TIMEOUT_MIN)),
            "version": int(data.get("version", 1)),
        }

    async def has_accepted(self, chat_id: int, user_id: int, version: int) -> bool:
        doc = await self.accepted_db.find_one({"chat_id": chat_id, "user_id": user_id})
        return bool(doc and doc.get("version", 0) >= version)

    async def _mark_accepted(self, chat_id: int, user_id: int, version: int) -> None:
        await self.accepted_db.update_one(
            {"chat_id": chat_id, "user_id": user_id},
            {"$set": {"version": version, "accepted_at": int(time.time())}},
            upsert=True,
        )
        await self.pending_db.delete_many({"chat_id": chat_id, "user_id": user_id})

    # }

    def _rich_tnc(self, chat_title: str, tnc: str, timeout: int, mention: str = "") -> str:
        rules = "".join(
            f"<li>{html.escape(line.split('. ', 1)[-1])}</li>"
            for line in tnc.splitlines()
            if line.strip()
        )
        hello = f"<p>Hey {mention}! " if mention else "<p>"
        return (
            f"<h2>📜 {html.escape(chat_title)}: Terms &amp; Conditions</h2>"
            f"{hello}Read these rules and press <b>I Agree</b> to join.</p>"
            f"<ol>{rules}</ol>"
            "<hr/>"
            f"<footer>⏳ You have {timeout} minutes. No reply means no entry.</footer>"
        )

    # { Flow 1: join requests
    async def on_chat_join_request(self, request: ChatJoinRequest) -> None:
        chat, user = request.chat, request.from_user
        conf = await self.settings(chat.id)
        if not conf["enabled"] or user.is_bot:
            return

        if await self.has_accepted(chat.id, user.id, conf["version"]):
            await self._approve(chat.id, user.id)
            return

        keyboard = [
            [btn("✅ I Agree", f"tnc_ok_{chat.id}", style="success")],
            [btn("❌ Decline", f"tnc_no_{chat.id}", style="danger")],
        ]
        if self.bot.config.TNC_URL:
            keyboard.insert(0, [btn("📖 Full rules", url=self.bot.config.TNC_URL, style="primary")])

        sent = await self.bot.botapi.send_rich(
            user.id, self._rich_tnc(chat.title or "the group", conf["text"], conf["timeout"]), keyboard=keyboard
        )
        if not sent:
            # Bot API could not reach the user; try MTProto, which has the requester's access hash
            try:
                await self.bot.client.send_message(
                    user.id,
                    f"**{chat.title}: Terms & Conditions**\n\n{conf['text']}\n\n"
                    f"Reply within {conf['timeout']} minutes.",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [InlineKeyboardButton("✅ I Agree", callback_data=f"tnc_ok_{chat.id}")],
                            [InlineKeyboardButton("❌ Decline", callback_data=f"tnc_no_{chat.id}")],
                        ]
                    ),
                )
            except (PeerIdInvalid, UserIsBlocked) as err:
                self.log.info("Can't DM join requester %s: %s", user.id, err)
                return  # leave the request for human admins

        await self.pending_db.update_one(
            {"chat_id": chat.id, "user_id": user.id},
            {"$set": {"kind": "request", "expires": time.time() + conf["timeout"] * 60}},
            upsert=True,
        )

    async def _approve(self, chat_id: int, user_id: int) -> bool:
        try:
            await self.bot.client.approve_chat_join_request(chat_id, user_id)
            return True
        except UserAlreadyParticipant:
            return True
        except (HideRequesterMissing, ChatAdminRequired) as err:
            self.log.info("Approve failed in %s for %s: %s", chat_id, user_id, err)
            return False

    async def _decline(self, chat_id: int, user_id: int) -> None:
        try:
            await self.bot.client.decline_chat_join_request(chat_id, user_id)
        except (HideRequesterMissing, ChatAdminRequired, UserAlreadyParticipant):
            pass

    # }

    # { Flow 2: direct joins
    @listener.priority(40)
    async def on_chat_action(self, message: Message) -> None:
        if not message.new_chat_members:
            return
        chat = message.chat
        conf = await self.settings(chat.id)
        if not conf["enabled"]:
            return

        for member in message.new_chat_members:
            if member.is_bot or member.id == self.bot.uid:
                continue
            if await self.has_accepted(chat.id, member.id, conf["version"]):
                continue
            await self._gate_member(chat, member, conf, message.message_thread_id)

    async def _gate_member(self, chat: Any, member: User, conf: MutableMapping[str, Any], thread_id: Optional[int]) -> None:
        try:
            await self.bot.client.restrict_chat_member(chat.id, member.id, ChatPermissions())
        except (ChatAdminRequired, UserNotParticipant) as err:
            self.log.info("Can't gate %s in %s: %s", member.id, chat.id, err)
            return

        mention = f'<a href="tg://user?id={member.id}">{html.escape(member.first_name or "there")}</a>'
        keyboard = [[btn("✅ I Agree", f"tnc_g_{chat.id}_{member.id}", style="success")]]
        if self.bot.config.TNC_URL:
            keyboard.append([btn("📖 Full rules", url=self.bot.config.TNC_URL, style="primary")])

        sent = await self.bot.botapi.send_rich(
            chat.id,
            self._rich_tnc(chat.title or "the group", conf["text"], conf["timeout"], mention),
            keyboard=keyboard,
            thread_id=thread_id,
        )
        await self.pending_db.update_one(
            {"chat_id": chat.id, "user_id": member.id},
            {
                "$set": {
                    "kind": "member",
                    "expires": time.time() + conf["timeout"] * 60,
                    "msg_id": sent.get("message_id") if sent else None,
                }
            },
            upsert=True,
        )

    # }

    @listener.filters(filters.regex(r"^tnc_(ok|no|g)_(-?\d+)(?:_(\d+))?$"))
    async def on_callback_query(self, query: CallbackQuery) -> None:
        action, chat_id, target = query.matches[0].group(1), int(query.matches[0].group(2)), query.matches[0].group(3)
        user = query.from_user
        conf = await self.settings(chat_id)

        if action == "g":
            if not target or int(target) != user.id:
                await query.answer("These rules are for the new member. 🙂", show_alert=True)
                return
            await self._mark_accepted(chat_id, user.id, conf["version"])
            try:
                await self.bot.client.unban_chat_member(chat_id, user.id)  # lifts restriction
            except ChatAdminRequired:
                pass
            await query.answer("✅ Thanks! You can chat now.")
            try:
                await query.message.delete()
            except MessageDeleteForbidden:
                pass
            return

        if action == "ok":
            await self._mark_accepted(chat_id, user.id, conf["version"])
            ok = await self._approve(chat_id, user.id)
            await query.answer("✅ Accepted" if ok else "Request expired, please ask to join again.")
            await self.bot.botapi.edit_text(
                query.message.chat.id,
                query.message.id,
                "✅ <b>Rules accepted.</b> Welcome to the group!" if ok
                else "⌛ Your join request expired. Please send a new request.",
            )
            return

        await self.pending_db.delete_many({"chat_id": chat_id, "user_id": user.id})
        await self._decline(chat_id, user.id)
        await query.answer("Declined")
        await self.bot.botapi.edit_text(
            query.message.chat.id, query.message.id, "❌ You declined the rules, so the join request was cancelled."
        )

    async def _sweep_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(30)
                now = time.time()
                async for doc in self.pending_db.find({"expires": {"$lt": now}}):
                    chat_id, user_id = doc["chat_id"], doc["user_id"]
                    if doc.get("kind") == "request":
                        await self._decline(chat_id, user_id)
                    else:
                        try:
                            await self.bot.client.ban_chat_member(chat_id, user_id)
                            await asyncio.sleep(1)
                            await self.bot.client.unban_chat_member(chat_id, user_id)
                        except (ChatAdminRequired, UserNotParticipant):
                            pass
                        if doc.get("msg_id"):
                            await self.bot.botapi.delete(chat_id, [doc["msg_id"]])
                    await self.pending_db.delete_one({"_id": doc["_id"]})
            except asyncio.CancelledError:
                return
            except Exception as err:  # skipcq: PYL-W0703
                self.log.error("T&C sweeper error: %s", err)

    # { commands
    @command.filters(filters.admin_only)
    async def cmd_tnc(self, ctx: command.Context) -> str:
        """/tnc on|off, or /tnc to see status"""
        chat = ctx.chat
        arg = (ctx.input or "").strip().lower()
        if arg in {"on", "yes", "enable"}:
            await self.db.update_one({"chat_id": chat.id}, {"$set": {"enabled": True}}, upsert=True)
            return (
                "✅ T&C gate is **on**.\n"
                "Best setup: turn on __Approve new members__ in group settings and give me the "
                "**Invite users** and **Ban users** admin rights. Direct joiners will be muted until they agree."
            )
        if arg in {"off", "no", "disable"}:
            await self.db.update_one({"chat_id": chat.id}, {"$set": {"enabled": False}}, upsert=True)
            return "T&C gate is **off**."

        conf = await self.settings(chat.id)
        return (
            f"T&C gate: **{'on' if conf['enabled'] else 'off'}** · timeout {conf['timeout']} min · "
            f"version {conf['version']}\n\n{conf['text']}"
        )

    @command.filters(filters.admin_only)
    async def cmd_settnc(self, ctx: command.Context) -> str:
        """Set the T&C text. Bumps the version so everyone must accept again on next join."""
        text = ctx.input
        if not text and ctx.msg.reply_to_message:
            text = ctx.msg.reply_to_message.text or ctx.msg.reply_to_message.caption
        if not text:
            return "Usage: `/settnc <rules, one per line>` or reply to a message."
        await self.db.update_one(
            {"chat_id": ctx.chat.id}, {"$set": {"text": str(text)}, "$inc": {"version": 1}}, upsert=True
        )
        return "📜 Terms & Conditions updated."

    @command.filters(filters.admin_only)
    async def cmd_resettnc(self, ctx: command.Context) -> str:
        await self.db.update_one({"chat_id": ctx.chat.id}, {"$unset": {"text": ""}}, upsert=True)
        return "Terms & Conditions reset to the default."

    @command.filters(filters.admin_only)
    async def cmd_tnctimeout(self, ctx: command.Context) -> str:
        try:
            minutes = max(1, min(60, int(ctx.input)))
        except (TypeError, ValueError):
            return "Usage: `/tnctimeout <1-60 minutes>`"
        await self.db.update_one({"chat_id": ctx.chat.id}, {"$set": {"timeout": minutes}}, upsert=True)
        return f"New members now get **{minutes} minutes** to accept."

    # }
