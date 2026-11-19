# meta developer: @realmyasnikov
# scope: hikka/heroku

import os
import tempfile

from telethon.tl.types import Message

from .. import loader, utils


@loader.tds
class TTLSaverMod(loader.Module):
    """Сохраняет самоудаляющиеся фото и видео в Избранное"""

    strings = {
        "name": "TTLSaver",
        "on": "✅ Сохранение TTL-медиа включено",
        "off": "❌ Сохранение TTL-медиа выключено",
        "already_on": "ℹ️ Уже включено",
        "already_off": "ℹ️ Уже выключено",
        "status_on": "📊 Статус: включено",
        "status_off": "📊 Статус: выключено",
        "caption": "💾 Сохранено {kind} от {name} (таймер {ttl} с)",
    }

    async def client_ready(self, client, db):
        self._client = client
        self._db = db

    def _enabled(self):
        return self._db.get(self.strings["name"], "enabled", True)

    @loader.command(ru_doc="Включить сохранение TTL-медиа")
    async def saveon(self, message: Message):
        """Enable saving of self-destructing media"""
        if self._enabled():
            await utils.answer(message, self.strings["already_on"])
            return
        self._db.set(self.strings["name"], "enabled", True)
        await utils.answer(message, self.strings["on"])

    @loader.command(ru_doc="Выключить сохранение TTL-медиа")
    async def saveoff(self, message: Message):
        """Disable saving of self-destructing media"""
        if not self._enabled():
            await utils.answer(message, self.strings["already_off"])
            return
        self._db.set(self.strings["name"], "enabled", False)
        await utils.answer(message, self.strings["off"])

    @loader.command(ru_doc="Показать статус сохранения TTL-медиа")
    async def savestatus(self, message: Message):
        """Show current status"""
        key = "status_on" if self._enabled() else "status_off"
        await utils.answer(message, self.strings[key])

    @loader.watcher("in", "only_media")
    async def watcher(self, message: Message):
        if not self._enabled():
            return

        ttl = getattr(message.media, "ttl_seconds", None)
        if not ttl:
            return

        if message.photo:
            kind = "фото"
        elif message.video or message.video_note:
            kind = "видео"
        else:
            return

        sender = await message.get_sender()
        name = getattr(sender, "first_name", None) or "unknown"

        tmpdir = tempfile.mkdtemp()
        try:
            path = await message.download_media(file=tmpdir + "/")
            if not path:
                return
            await self._client.send_file(
                "me",
                path,
                caption=self.strings["caption"].format(
                    kind=kind, name=name, ttl=ttl
                ),
                supports_streaming=bool(message.video),
            )
        finally:
            for f in os.listdir(tmpdir):
                os.remove(os.path.join(tmpdir, f))
            os.rmdir(tmpdir)
