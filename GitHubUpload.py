# meta developer: @realmyasnikov
# requires: aiohttp

import base64
import io

import aiohttp
from telethon.tl.types import Message

from .. import loader, utils


@loader.tds
class GitHubUploadMod(loader.Module):
    """Загружает новые модули (.py) в репозиторий GitHub"""

    strings = {"name": "GitHubUpload"}

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "token",
                None,
                "GitHub token (право repo)",
                validator=loader.validators.Hidden(),
            ),
            loader.ConfigValue(
                "repo",
                "",
                "Репозиторий: владелец/репозиторий",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "branch",
                "main",
                "Ветка",
                validator=loader.validators.String(),
            ),
        )

    async def _upload(self, name: str, data: bytes):
        repo = self.config["repo"].strip().strip("/")
        branch = self.config["branch"].strip()
        url = f"https://api.github.com/repos/{repo}/contents/{name}"
        headers = {
            "Authorization": f"Bearer {self.config['token']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            sha = None
            async with session.get(url, params={"ref": branch}) as r:
                if r.status == 200:
                    sha = (await r.json()).get("sha")

            payload = {
                "message": f"{'Update' if sha else 'Add'} {name}",
                "content": base64.b64encode(data).decode(),
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha

            async with session.put(url, json=payload) as r:
                body = await r.json()
                if r.status in (200, 201):
                    raw = f"https://raw.githubusercontent.com/{repo}/{branch}/{name}"
                    return True, ("обновлён" if sha else "добавлен"), raw
                return False, body.get("message", f"HTTP {r.status}"), None

    @loader.command(ru_doc="(в ответ на .py файл) загрузить модуль на GitHub")
    async def ghup(self, message: Message):
        """(reply to a .py file) upload the module to GitHub"""
        if not self.config["token"]:
            await utils.answer(message, "❌ Укажи токен: <code>.cfg GitHubUpload</code>")
            return

        if not self.config["repo"] or "/" not in self.config["repo"]:
            await utils.answer(
                message,
                "❌ Укажи репозиторий в <code>.cfg GitHubUpload</code> "
                "в формате <code>ник/репозиторий</code>",
            )
            return

        reply = await message.get_reply_message()
        if not reply or not reply.file:
            await utils.answer(message, "❌ Ответь командой на .py файл с модулем")
            return

        name = utils.get_args_raw(message).strip() or reply.file.name or ""
        if not name.endswith(".py"):
            await utils.answer(message, "❌ Нужен файл .py")
            return

        await utils.answer(message, "⏳ Загружаю на GitHub...")

        buf = io.BytesIO()
        await self._client.download_media(reply, buf)

        ok, info, raw = await self._upload(name, buf.getvalue())

        if ok:
            await utils.answer(
                message,
                f"✅ Модуль <b>{utils.escape_html(name)}</b> {info}\n"
                f"🔗 <code>{raw}</code>\n\n"
                f"Установка: <code>.dlm {raw}</code>",
            )
        else:
            await utils.answer(message, f"❌ Ошибка GitHub: <code>{utils.escape_html(info)}</code>")
