import time

from .http import HttpError, Transport
from .models import Page


class WikiError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(f"MediaWiki : {code}")


class WikiClient:
    def __init__(self, settings, transport: Transport):
        self.settings, self.http = settings, transport

    def api(self, params: dict, *, write: bool = False) -> dict:
        payload = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        attempts = 1 if write else self.settings.max_retries
        for attempt in range(attempts):
            response = self.http.request("POST" if write else "GET", self.settings.wiki_api,
                data=payload if write else None, params=None if write else payload, retry=not write)
            try:
                result = response.json()
            except ValueError:
                raise HttpError("Réponse MediaWiki JSON invalide") from None
            if "error" not in result:
                return result
            code = result["error"].get("code", "unknown")
            if code in {"maxlag", "ratelimited", "readonly"} and attempt + 1 < attempts:
                self.http.sleep(min(2 ** (attempt + 1), 32))
                continue
            raise WikiError(code)
        raise WikiError("retry-exhausted")

    def category_members(self) -> list[dict]:
        params = {"action": "query", "list": "categorymembers", "cmtitle": self.settings.category,
                  "cmprop": "ids|title|timestamp", "cmsort": "timestamp", "cmdir": "desc",
                  "cmnamespace": "0", "cmtype": "page", "cmlimit": "500"}
        result, continuation = [], {}
        while True:
            batch = self.api({**params, **continuation})
            result.extend(batch["query"]["categorymembers"])
            if "continue" not in batch:
                return result
            continuation = batch["continue"]

    def page(self, *, title: str | None = None, page_id: int | None = None) -> Page:
        if (title is None) == (page_id is None):
            raise ValueError("Donner un titre ou un page_id")
        params = {"action": "query", "prop": "revisions|categories", "rvprop": "ids|timestamp|content",
                  "rvslots": "main", "curtimestamp": "1", "cllimit": "500"}
        params.update({"titles": title} if title is not None else {"pageids": str(page_id)})
        response = self.api(params)
        pages = response.get("query", {}).get("pages", [])
        if len(pages) != 1 or pages[0].get("missing") or not pages[0].get("revisions"):
            raise WikiError("missing-or-hidden-page")
        info = pages[0]
        revision = info["revisions"][0]
        content = revision.get("slots", {}).get("main", {}).get("content")
        if not isinstance(content, str):
            raise WikiError("hidden-content")
        categories = [c["title"] for c in info.get("categories", [])]
        continuation = response.get("continue")
        while continuation:
            extra = self.api({"action": "query", "prop": "categories", "pageids": str(info["pageid"]), "cllimit": "500", **continuation})
            categories.extend(c["title"] for c in extra["query"]["pages"][0].get("categories", []))
            continuation = extra.get("continue")
        return Page(info["pageid"], info["title"], revision["revid"], revision["timestamp"], response["curtimestamp"], content, info["ns"], tuple(categories))

    def login(self):
        if not self.settings.bot_login or not self.settings.bot_password or not self.settings.bot_account:
            raise ValueError("Renseigner WIKI_BOT_LOGIN, WIKI_BOT_PASSWORD et WIKI_BOT_ACCOUNT")
        token = self.api({"action": "query", "meta": "tokens", "type": "login"})["query"]["tokens"]["logintoken"]
        result = self.api({"action": "login", "lgname": self.settings.bot_login,
                           "lgpassword": self.settings.bot_password, "lgtoken": token}, write=True)
        if result.get("login", {}).get("result") != "Success":
            raise WikiError("login-failed")
        self.check_account()

    def check_account(self):
        info = self.api({"action": "query", "meta": "userinfo", "uiprop": "blockinfo|rights"})["query"]["userinfo"]
        if info.get("anon") or info.get("name", "").replace("_", " ") != self.settings.bot_account.replace("_", " "):
            raise WikiError("wrong-account")
        if any(k in info for k in ("blockid", "blockedby", "blockreason")):
            raise WikiError("blocked")
        if "bot" not in info.get("rights", []):
            raise WikiError("missing-bot-right")

    def edit(self, page: Page, new_text: str, summary: str) -> int:
        self.check_account()
        csrf = self.api({"action": "query", "meta": "tokens", "type": "csrf", "assert": "bot",
                         "assertuser": self.settings.bot_account})["query"]["tokens"]["csrftoken"]
        data = {"action": "edit", "pageid": str(page.page_id), "text": new_text, "summary": summary,
                "token": csrf, "baserevid": str(page.revision_id), "basetimestamp": page.timestamp,
                "starttimestamp": page.start_timestamp, "assert": "bot", "assertuser": self.settings.bot_account,
                "bot": "1", "minor": "1", "nocreate": "1", "watchlist": "nochange"}
        # Une soumission HTTP ne sera jamais retentée automatiquement.
        result = self.api(data, write=True).get("edit", {})
        if result.get("result") != "Success" or "newrevid" not in result:
            raise WikiError("edit-not-confirmed")
        return result["newrevid"]
