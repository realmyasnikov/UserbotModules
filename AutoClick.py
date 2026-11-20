# meta developer: @realmyasnikov
# scope: hikka_only

import asyncio
import logging
import re

from telethon import utils as tutils
from telethon.errors import BotResponseTimeoutError
from telethon.tl.types import Message

from .. import loader, utils

logger = logging.getLogger(__name__)


@loader.tds
class AutoClickMod(loader.Module):
    """Automatically clicks inline buttons in messages"""

    strings = {
        "name": "AutoClick",
        "usage_new": (
            "<b>Usage:</b> <code>.acnew chat_id message text | button text</code>\n"
            "Message text can be empty: <code>.acnew chat_id | button text</code>"
        ),
        "usage_nums": (
            "<b>Usage:</b> <code>.{cmd} 1</code> or <code>.{cmd} 1 2 3</code> "
            "(several rules, separated by space, comma or /)\n"
            "Numbers are shown in <code>.aclist</code>"
        ),
        "bad_nums": "No such rule number. Total rules: {}",
        "no_chat": "Chat not found: <code>{}</code>",
        "added": (
            "<b>AutoClick enabled</b> - rule #{}\nChat: <code>{}</code>\n"
            "Message: <code>{}</code>\nButton: <code>{}</code>\n\n{}"
        ),
        "res_ok": "Clicked right now: <b>{}</b>",
        "res_no_msg": (
            "No message with this text and button in the last 50 messages. "
            "Waiting for a new one"
        ),
        "res_err": "Click error: <code>{}</code>",
        "any": "any",
        "paused": "<b>Paused:</b> {}",
        "resumed": "<b>Started:</b> {}",
        "deleted": "<b>Deleted:</b> {}",
        "empty": "No rules",
        "list_head": "<b>Rules:</b>",
        "paused_mark": "[paused]",
        "btn_pause": "Pause",
        "btn_start": "Start",
        "gone": "Rule not found",
        "cfg_delay": "Delay before click (seconds)",
        "cfg_own": "Also click buttons in your own messages",
    }

    strings_ru = {
        "usage_new": (
            "<b>Использование:</b> <code>.acnew id_чата текст сообщения | текст кнопки</code>\n"
            "Текст сообщения можно не указывать: <code>.acnew id_чата | текст кнопки</code>"
        ),
        "usage_nums": (
            "<b>Использование:</b> <code>.{cmd} 1</code> или <code>.{cmd} 1 2 3</code> "
            "(несколько правил, через пробел, запятую или /)\n"
            "Номера видны в <code>.aclist</code>"
        ),
        "bad_nums": "Нет правила с таким номером. Всего правил: {}",
        "no_chat": "Чат не найден: <code>{}</code>",
        "added": (
            "<b>АвтоКлик включен</b> - правило №{}\nЧат: <code>{}</code>\n"
            "Сообщение: <code>{}</code>\nКнопка: <code>{}</code>\n\n{}"
        ),
        "res_ok": "Сейчас нажата кнопка: <b>{}</b>",
        "res_no_msg": (
            "В последних 50 сообщениях нет сообщения с таким текстом и кнопкой. "
            "Жду новое"
        ),
        "res_err": "Ошибка нажатия: <code>{}</code>",
        "any": "любое",
        "paused": "<b>Пауза:</b> {}",
        "resumed": "<b>Старт:</b> {}",
        "deleted": "<b>Удалено:</b> {}",
        "empty": "Нет правил",
        "list_head": "<b>Правила:</b>",
        "paused_mark": "[пауза]",
        "btn_pause": "Пауза",
        "btn_start": "Старт",
        "gone": "Правило не найдено",
        "cfg_delay": "Задержка перед нажатием (секунды)",
        "cfg_own": "Нажимать кнопки и в своих сообщениях",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "delay",
                1.0,
                lambda: self.strings("cfg_delay"),
                validator=loader.validators.Float(minimum=0),
            ),
            loader.ConfigValue(
                "click_own",
                False,
                lambda: self.strings("cfg_own"),
                validator=loader.validators.Boolean(),
            ),
        )
        self._clicked = set()

    async def client_ready(self, client, db):
        self._client = client
        self._db = db

    # flat list: [{"chat": str, "msg": str, "btn": str, "off": bool}, ...]
    # the rule number is its position in this list + 1
    def _rules(self) -> list:
        data = self._db.get(self.strings["name"], "rules", [])
        if isinstance(data, dict):  # migrate the old chat -> rules format
            data = [dict(chat=k, **r) for k, lst in data.items() for r in lst]
            self._save(data)
        return data

    def _save(self, rules: list):
        self._db.set(self.strings["name"], "rules", rules)

    async def _resolve(self, raw: str):
        try:
            chat = int(raw)
        except ValueError:
            chat = raw
        try:
            return await self._client.get_entity(chat)
        except Exception:
            return None

    def _parse_numbers(self, raw: str, total: int):
        """'1', '1 2 3', '1,2,3' or '1/2/3' -> sorted rule numbers, or None"""
        tokens = [t for t in re.split(r"[\s,/]+", raw.strip()) if t]
        if not tokens:
            return None
        nums = set()
        for t in tokens:
            if not t.isdigit() or not 1 <= int(t) <= total:
                return None
            nums.add(int(t))
        return sorted(nums)

    async def _numbers_from_command(self, message: Message, cmd: str):
        """Returns (rules, numbers) or None when an error answer was sent"""
        rules = self._rules()
        raw = utils.get_args_raw(message)
        if not raw:
            await utils.answer(message, self.strings("usage_nums").format(cmd=cmd))
            return None
        nums = self._parse_numbers(raw, len(rules))
        if not nums:
            await utils.answer(message, self.strings("bad_nums").format(len(rules)))
            return None
        return rules, nums

    async def _get_buttons(self, msg: Message):
        """msg.buttons can be None when the chat is not cached, so fetch it"""
        if not msg.reply_markup:
            return None
        if msg.buttons:
            return msg.buttons
        try:
            return await msg.get_buttons()
        except Exception:
            logger.exception("AutoClick: get_buttons failed")
            return None

    async def _click_button(self, msg: Message, rule: dict):
        """Returns ("ok", text), ("no_btn", None) or ("error", text)"""
        buttons = await self._get_buttons(msg)
        if not buttons:
            return "no_btn", None

        for row in buttons:
            for button in row:
                if rule["btn"] and rule["btn"].lower() not in (button.text or "").lower():
                    continue
                try:
                    await button.click()
                except BotResponseTimeoutError:
                    pass  # the bot got the click but did not answer the callback
                except Exception as e:
                    logger.exception("AutoClick: failed to click %r", button.text)
                    return "error", f"{type(e).__name__}: {e}"
                return "ok", button.text or ""
        return "no_btn", None

    async def _click_existing(self, entity, rule: dict):
        """Clicks the latest matching message that is already in the chat"""
        async for msg in self._client.iter_messages(entity, limit=50):
            if not msg.reply_markup:
                continue
            if rule["msg"] and rule["msg"].lower() not in (msg.raw_text or "").lower():
                continue
            status = await self._click_button(msg, rule)
            if status[0] == "no_btn":
                continue
            return status
        return "no_msg", None

    @loader.command(
        ru_doc="<id чата> <текст сообщения> | <текст кнопки> - добавить новое правило"
    )
    async def acnew(self, message: Message):
        """<chat id> <message text> | <button text> - add a new rule"""
        parts = utils.get_args_raw(message).split(maxsplit=1)
        if len(parts) < 2 or "|" not in parts[1]:
            await utils.answer(message, self.strings("usage_new"))
            return

        chat_raw = parts[0]
        msg_text, btn_text = [x.strip() for x in parts[1].split("|", 1)]

        entity = await self._resolve(chat_raw)
        if entity is None:
            await utils.answer(message, self.strings("no_chat").format(chat_raw))
            return

        key = str(tutils.get_peer_id(entity))
        rules = self._rules()

        for i, rule in enumerate(rules):
            if (rule["chat"], rule["msg"], rule["btn"]) == (key, msg_text, btn_text):
                rule["off"] = False  # the same rule again just starts it
                number = i + 1
                break
        else:
            rule = {"chat": key, "msg": msg_text, "btn": btn_text, "off": False}
            rules.append(rule)
            number = len(rules)
        self._save(rules)

        state, info = await self._click_existing(entity, rule)
        if state == "ok":
            result = self.strings("res_ok").format(utils.escape_html(info))
        elif state == "error":
            result = self.strings("res_err").format(utils.escape_html(info))
        else:
            result = self.strings("res_no_msg")

        await utils.answer(
            message,
            self.strings("added").format(
                number,
                key,
                utils.escape_html(msg_text) or self.strings("any"),
                utils.escape_html(btn_text) or self.strings("any"),
                result,
            ),
        )

    @loader.command(ru_doc="<номера> - запустить правила (1 или 1 2 3)")
    async def acon(self, message: Message):
        """<numbers> - start rules (1 or 1 2 3)"""
        data = await self._numbers_from_command(message, "acon")
        if data is None:
            return
        rules, nums = data
        for n in nums:
            rules[n - 1]["off"] = False
        self._save(rules)
        await utils.answer(
            message, self.strings("resumed").format(", ".join(f"#{n}" for n in nums))
        )

    @loader.command(ru_doc="<номера> - поставить правила на паузу (1 или 1 2 3)")
    async def acoff(self, message: Message):
        """<numbers> - pause rules (1 or 1 2 3)"""
        data = await self._numbers_from_command(message, "acoff")
        if data is None:
            return
        rules, nums = data
        for n in nums:
            rules[n - 1]["off"] = True
        self._save(rules)
        await utils.answer(
            message, self.strings("paused").format(", ".join(f"#{n}" for n in nums))
        )

    @loader.command(ru_doc="<номера> - удалить правила (1 или 1 2 3)")
    async def acdel(self, message: Message):
        """<numbers> - delete rules (1 or 1 2 3)"""
        data = await self._numbers_from_command(message, "acdel")
        if data is None:
            return
        rules, nums = data
        for n in reversed(nums):
            rules.pop(n - 1)
        self._save(rules)
        await utils.answer(
            message, self.strings("deleted").format(", ".join(f"#{n}" for n in nums))
        )

    def _render(self):
        """Builds the list text and one pause/start button per rule"""
        rules = self._rules()
        if not rules:
            return self.strings("empty"), []

        lines = [self.strings("list_head")]
        markup = []
        for i, r in enumerate(rules, start=1):
            off = r.get("off")
            mark = f" {self.strings('paused_mark')}" if off else ""
            msg_t = utils.escape_html(r["msg"]) or self.strings("any")
            btn_t = utils.escape_html(r["btn"]) or self.strings("any")
            lines.append(f"<b>#{i}</b> <code>{r['chat']}</code>: {msg_t} | {btn_t}{mark}")

            action = self.strings("btn_start" if off else "btn_pause")
            markup.append(
                [
                    {
                        "text": f"#{i} {action}: {r['btn'] or self.strings('any')}",
                        "callback": self._toggle,
                        "args": (r["chat"], r["msg"], r["btn"]),
                    }
                ]
            )
        return "\n".join(lines), markup

    async def _toggle(self, call, chat: str, msg: str, btn: str):
        rules = self._rules()
        for rule in rules:
            if (rule["chat"], rule["msg"], rule["btn"]) == (chat, msg, btn):
                rule["off"] = not rule.get("off")
                break
        else:
            await call.answer(self.strings("gone"), show_alert=True)
            return
        self._save(rules)

        text, markup = self._render()
        await call.edit(text, reply_markup=markup)

    @loader.command(ru_doc="Все правила с номерами и кнопками пауза/старт")
    async def aclist(self, message: Message):
        """All rules with numbers and pause/start buttons"""
        text, markup = self._render()
        if not markup:
            await utils.answer(message, text)
            return

        try:
            await self.inline.form(text=text, message=message, reply_markup=markup)
        except Exception:
            logger.exception("AutoClick: inline form failed")
            await utils.answer(message, text)

    @loader.watcher(only_messages=True)
    async def watcher(self, message: Message):
        if not message.reply_markup:
            return
        if message.out and not self.config["click_own"]:
            return

        chat = str(message.chat_id)
        text = (message.raw_text or "").lower()

        for rule in self._rules():
            if rule["chat"] != chat or rule.get("off"):
                continue
            if rule["msg"] and rule["msg"].lower() not in text:
                continue

            marker = (message.chat_id, message.id, rule["msg"], rule["btn"])
            if marker in self._clicked:
                continue
            self._clicked.add(marker)
            if len(self._clicked) > 2000:
                self._clicked.clear()

            await asyncio.sleep(self.config["delay"])
            state, info = await self._click_button(message, rule)
            if state == "ok":
                logger.info("AutoClick: clicked %r in %s", info, message.chat_id)
