# meta developer: @your_username
# scope: hikka_only
# meta pic: https://img.icons8.com/color/48/000000/note.png
# meta banner: https://i.imgur.com/linked_banner.jpg

from telethon.tl.types import Message, MessageEntityBold, MessageEntityItalic
from .. import loader, utils

@loader.tds
class MediaNoteMod(loader.Module):
    """Модуль для одной медиа-заметки: сохранить, отправить, удалить (от своего имени)"""

    strings = {
        "name": "MediaNote",
        "no_reply": "🚫 <b>Ответь на сообщение, чтобы сохранить заметку.</b>",
        "saved": "✅ <b>Заметка сохранена.</b>",
        "not_found": "🚫 <b>Заметка пуста. Сначала сохрани через <code>.з</code> (реплаем).</b>",
        "deleted": "🗑 <b>Заметка удалена.</b>",
        "forward_error": "🚫 <b>Не удалось отправить. Возможно, сообщение удалено или нет доступа.</b>"
    }

    def __init__(self):
        self.note = {}

    async def client_ready(self, client, db):
        self._client = client
        self.db = db
        saved = db.get(self.__class__.__name__, "note", {})
        if saved and isinstance(saved, dict):
            self.note = saved

    async def on_unload(self):
        if hasattr(self, "db") and self.db:
            self.db.set(self.__class__.__name__, "note", self.note)

    def _parse_markers(self, args: str):
        """Парсит: цифра → X Серия, ж/к/жк → форматирование, иначе обычный текст"""
        if not args:
            return None, None

        args = args.strip()

        # Цифра → X Серия жирным
        if args.isdigit():
            caption = f"{args} Серия"
            return caption, [MessageEntityBold(offset=0, length=len(caption))]

        # Маркеры ж/к/жк
        parts = args.split(maxsplit=1)
        marker = parts[0].lower()
        text = parts[1] if len(parts) > 1 else ""

        entities = []

        if marker in ("жк", "кж"):
            if text:
                entities.append(MessageEntityBold(offset=0, length=len(text)))
                entities.append(MessageEntityItalic(offset=0, length=len(text)))
            return text if text else None, entities if entities else None
        elif marker == "ж":
            if text:
                entities.append(MessageEntityBold(offset=0, length=len(text)))
            return text if text else None, entities if entities else None
        elif marker == "к":
            if text:
                entities.append(MessageEntityItalic(offset=0, length=len(text)))
            return text if text else None, entities if entities else None
        else:
            return args, None

    @loader.command(ru_doc="— сохранить заметку (реплаем на сообщение)")
    async def з(self, message: Message):
        """Сохранить одну заметку — .з (реплаем)"""
        reply = await message.get_reply_message()
        if not reply:
            await utils.answer(message, self.strings("no_reply"))
            return

        self.note = {
            "chat_id": reply.chat_id,
            "msg_id": reply.id
        }

        await utils.answer(message, self.strings("saved"))

    @loader.command(ru_doc="[цифра/ж/к/жк] [текст] — отправить заметку")
    async def о(self, message: Message):
        """Отправить заметку — .о [цифра/ж/к/жк] [текст]"""
        if not self.note or "chat_id" not in self.note or "msg_id" not in self.note:
            await utils.answer(message, self.strings("not_found"))
            return

        args = utils.get_args_raw(message)

        try:
            orig_msg = await self._client.get_messages(
                self.note["chat_id"],
                ids=self.note["msg_id"]
            )
            if not orig_msg:
                await utils.answer(message, self.strings("forward_error"))
                return

            if args:
                text, entities = self._parse_markers(args)
            else:
                text = None
                entities = None

            if orig_msg.media:
                sent = await self._client.send_file(
                    message.to_id,
                    orig_msg.media,
                    caption=text if text else "",
                    reply_to=message.reply_to_msg_id or message.id
                )
                if entities and text:
                    await sent.edit(text, formatting_entities=entities)
            else:
                if text:
                    await self._client.send_message(
                        message.to_id,
                        text,
                        formatting_entities=entities if entities else None,
                        reply_to=message.reply_to_msg_id or message.id
                    )
                elif orig_msg.raw_text:
                    await self._client.send_message(
                        message.to_id,
                        orig_msg.raw_text,
                        reply_to=message.reply_to_msg_id or message.id
                    )

        except Exception as e:
            await utils.answer(message, f"🚫 <b>Ошибка:</b> <code>{e}</code>")
            return

        if message.out:
            await message.delete()

    @loader.command(ru_doc="— удалить заметку")
    async def дз(self, message: Message):
        """Удалить заметку — .дз"""
        self.note = {}
        await utils.answer(message, self.strings("deleted"))