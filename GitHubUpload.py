# meta developer: @realmyasnikov
# requires: aiohttp

import asyncio
import base64
import io

import aiohttp
from telethon.tl.types import Message

from .. import loader, utils


@loader.tds
class GitHubUploadMod(loader.Module):
    """Загружает модули (.py) в репозиторий GitHub, удаляет их и показывает список"""

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

    def _config_error(self):
        if not self.config["token"]:
            return "❌ Укажи токен: <code>.cfg GitHubUpload</code>"
        if not self.config["repo"] or "/" not in self.config["repo"]:
            return (
                "❌ Укажи репозиторий в <code>.cfg GitHubUpload</code> "
                "в формате <code>ник/репозиторий</code>"
            )
        return None

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.config['token']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _repo(self):
        return self.config["repo"].strip().strip("/")

    def _branch(self):
        return self.config["branch"].strip()

    @staticmethod
    def _fix_name(name: str) -> str:
        name = name.strip()
        if name and not name.endswith(".py"):
            name += ".py"
        return name

    async def _upload(self, name: str, data: bytes, commit_msg: str):
        repo, branch = self._repo(), self._branch()
        url = f"https://api.github.com/repos/{repo}/contents/{name}"

        async with aiohttp.ClientSession(headers=self._headers()) as session:
            sha = None
            async with session.get(url, params={"ref": branch}) as r:
                if r.status == 200:
                    sha = (await r.json()).get("sha")

            payload = {
                "message": commit_msg or f"{'Update' if sha else 'Add'} {name}",
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

    async def _delete(self, name: str):
        repo, branch = self._repo(), self._branch()
        url = f"https://api.github.com/repos/{repo}/contents/{name}"

        async with aiohttp.ClientSession(headers=self._headers()) as session:
            async with session.get(url, params={"ref": branch}) as r:
                if r.status == 404:
                    return False, "файл не найден в репозитории"
                if r.status != 200:
                    body = await r.json()
                    return False, body.get("message", f"HTTP {r.status}")
                sha = (await r.json()).get("sha")

            payload = {"message": f"Delete {name}", "sha": sha, "branch": branch}
            async with session.delete(url, json=payload) as r:
                if r.status == 200:
                    return True, None
                body = await r.json()
                return False, body.get("message", f"HTTP {r.status}")

    @loader.command(
        ru_doc="[название.py] [commit message] - (в ответ на .py файл) загрузить модуль на GitHub"
    )
    async def ghub(self, message: Message):
        """[name.py] [commit message] - (reply to a .py file) upload the module to GitHub"""
        err = self._config_error()
        if err:
            await utils.answer(message, err)
            return

        reply = await message.get_reply_message()
        if not reply or not reply.file:
            # файл может быть в самом сообщении с командой (подпись к файлу)
            reply = message if message.file else None
        if not reply:
            await utils.answer(
                message,
                "❌ Файл не найден. Ответь командой на файл .py "
                "или отправь файл с подписью <code>.ghub</code>",
            )
            return

        args = utils.get_args_raw(message).strip()
        parts = args.split(maxsplit=1)
        if parts and parts[0].lower().endswith(".py"):
            # первое слово - название файла, дальше commit message
            name = parts[0]
            commit_msg = parts[1].strip() if len(parts) > 1 else ""
        else:
            # название не указано - берём имя файла, весь текст = commit message
            name = (reply.file.name or "").strip()
            commit_msg = args
            if not name and (reply.file.mime_type or "") in (
                "text/x-python",
                "text/x-script.python",
                "application/x-python-code",
            ):
                name = "module.py"

        if not name.lower().endswith(".py"):
            await utils.answer(
                message,
                "❌ Нужен файл .py\n"
                f"Имя файла: <code>{utils.escape_html(name or 'не определено')}</code>\n"
                "Можно задать вручную: <code>.ghub название.py</code>",
            )
            return

        await utils.answer(message, "⏳ Загружаю на GitHub...")

        buf = io.BytesIO()
        await self._client.download_media(reply, buf)

        ok, info, raw = await self._upload(name, buf.getvalue(), commit_msg)

        if ok:
            await utils.answer(
                message,
                f"✅ Модуль <b>{utils.escape_html(name)}</b> {info}\n"
                f"🔗 <code>{raw}</code>\n\n"
                f"Установка: <code>.dlm {raw}</code>",
            )
        else:
            await utils.answer(message, f"❌ Ошибка GitHub: <code>{utils.escape_html(info)}</code>")

    @loader.command(ru_doc="[название] - удалить модуль из репозитория GitHub")
    async def delhub(self, message: Message):
        """[name] - delete a module from the GitHub repository"""
        err = self._config_error()
        if err:
            await utils.answer(message, err)
            return

        args = utils.get_args_raw(message).strip()
        if not args:
            await utils.answer(message, "❌ Укажи название: <code>.delhub название</code>")
            return

        name = self._fix_name(args.split()[0])

        await utils.answer(message, "⏳ Удаляю...")
        ok, info = await self._delete(name)

        if ok:
            await utils.answer(message, f"🗑 Модуль <b>{utils.escape_html(name)}</b> удалён из репозитория")
        else:
            await utils.answer(message, f"❌ Ошибка GitHub: <code>{utils.escape_html(info)}</code>")

    async def _list(self):
        repo, branch = self._repo(), self._branch()
        base = f"https://api.github.com/repos/{repo}"

        async with aiohttp.ClientSession(headers=self._headers()) as session:
            async with session.get(f"{base}/contents/", params={"ref": branch}) as r:
                body = await r.json()
                if r.status != 200:
                    msg = body.get("message") if isinstance(body, dict) else None
                    return None, msg or f"HTTP {r.status}"

            files = [
                f for f in body
                if f.get("type") == "file" and f["name"].lower().endswith(".py")
            ]

            async def last_commit(f):
                params = {"path": f["path"], "sha": branch, "per_page": 1}
                async with session.get(f"{base}/commits", params=params) as r:
                    if r.status == 200:
                        data = await r.json()
                        if data:
                            c = data[0]["commit"]
                            return f["name"], c["message"].split("\n")[0], c["committer"]["date"]
                return f["name"], "", ""

            results = await asyncio.gather(*(last_commit(f) for f in files))

        # сначала самые свежие
        results = sorted(results, key=lambda x: x[2], reverse=True)
        return results, None

    @loader.command(ru_doc="показать модули из репозитория GitHub")
    async def gitlist(self, message: Message):
        """show modules from the GitHub repository"""
        err = self._config_error()
        if err:
            await utils.answer(message, err)
            return

        await utils.answer(message, "⏳ Загружаю список...")
        results, error = await self._list()

        if error:
            await utils.answer(message, f"❌ Ошибка GitHub: <code>{utils.escape_html(error)}</code>")
            return

        if not results:
            await utils.answer(message, "📭 В репозитории пока нет модулей .py")
            return

        repo, branch = self._repo(), self._branch()
        blocks = []
        for name, commit, _ in results:
            raw = f"https://raw.githubusercontent.com/{repo}/{branch}/{name}"
            blocks.append(
                f"📦 <b>{utils.escape_html(name)}</b>\n"
                f"💬 {utils.escape_html(commit) if commit else '-'}\n"
                f"🔗 <code>.dlm {raw}</code>"
            )

        # режем на сообщения до лимита Telegram
        chunks, current = [], f"📚 <b>Модули в {utils.escape_html(repo)}</b> ({len(blocks)}):\n\n"
        for b in blocks:
            if len(current) + len(b) + 2 > 3800:
                chunks.append(current)
                current = ""
            current += b + "\n\n"
        chunks.append(current)

        await utils.answer(message, chunks[0].rstrip())
        for chunk in chunks[1:]:
            await message.respond(chunk.rstrip())
