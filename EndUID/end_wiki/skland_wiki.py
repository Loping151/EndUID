"""Skland Wiki API client (anonymous auth, no user cred needed)."""
import hashlib
import hmac
import json
import time
from typing import Optional

import aiohttp

from gsuid_core.logger import logger

from ..utils.api.request_util import get_device_id

WIKI_API_BASE = "https://zonai.skland.com"
WIKI_AUTH_REFRESH = "/web/v1/auth/refresh"
WIKI_ITEM_INFO = "/web/v1/wiki/item/info"
WIKI_ITEM_CATALOG = "/web/v1/wiki/item/catalog"

WIKI_ORIGIN = "https://wiki.skland.com"
WIKI_REFERER = "https://wiki.skland.com/"
WIKI_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)

# Token expires after ~30 minutes; refresh at 25 min
TOKEN_TTL = 25 * 60


class SklandWikiClient:
    """Anonymous Skland wiki API client."""

    def __init__(self) -> None:
        self._did: str = ""
        self._token: str = ""
        self._token_time: float = 0
        self._session: Optional[aiohttp.ClientSession] = None
        self._catalog_cache: list[dict] = []
        self._catalog_cache_time: float = 0

    # ---- session ----

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20),
            )
        return self._session

    # ---- device id ----

    def _ensure_did(self) -> str:
        if not self._did:
            try:
                self._did = get_device_id(
                    user_agent=WIKI_USER_AGENT,
                    referer=WIKI_REFERER,
                )
            except Exception as e:
                logger.warning(f"[SklandWiki] dId generation failed: {e}")
                self._did = ""
        return self._did

    # ---- signing ----

    def _sign(self, path: str, query: str, token: str) -> dict:
        ts = str(int(time.time()))
        did = self._ensure_did()
        header_obj = {
            "platform": "3",
            "timestamp": ts,
            "dId": did,
            "vName": "1.0.0",
        }
        header_json = json.dumps(header_obj, separators=(",", ":"))
        sign_string = path + query + ts + header_json
        hmac_hash = hmac.new(
            token.encode(), sign_string.encode(), hashlib.sha256
        ).hexdigest()
        sign = hashlib.md5(hmac_hash.encode()).hexdigest()
        return {"timestamp": ts, "sign": sign, "dId": did}

    def _headers(self, sign_data: dict) -> dict:
        return {
            "User-Agent": WIKI_USER_AGENT,
            "Content-Type": "application/json",
            "Origin": WIKI_ORIGIN,
            "Referer": WIKI_REFERER,
            "platform": "3",
            "vName": "1.0.0",
            "timestamp": sign_data["timestamp"],
            "sign": sign_data["sign"],
            "dId": sign_data["dId"],
        }

    # ---- token ----

    async def _refresh_token(self) -> str:
        """Get anonymous session token via web/v1/auth/refresh."""
        sign_data = self._sign(WIKI_AUTH_REFRESH, "", "")
        headers = self._headers(sign_data)
        session = await self._get_session()
        url = f"{WIKI_API_BASE}{WIKI_AUTH_REFRESH}"
        try:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                if data.get("code") == 0:
                    self._token = data["data"]["token"]
                    self._token_time = time.time()
                    logger.info("[SklandWiki] Token refreshed")
                    return self._token
                logger.warning(
                    f"[SklandWiki] Token refresh failed: {data}"
                )
        except Exception as e:
            logger.error(f"[SklandWiki] Token refresh error: {e}")
        return ""

    async def _ensure_token(self) -> str:
        if not self._token or (time.time() - self._token_time) > TOKEN_TTL:
            await self._refresh_token()
        return self._token

    # ---- API requests ----

    async def _get(self, path: str, query: str = "") -> Optional[dict]:
        token = await self._ensure_token()
        if not token:
            return None
        sign_data = self._sign(path, query, token)
        headers = self._headers(sign_data)
        url = f"{WIKI_API_BASE}{path}"
        if query:
            url += f"?{query}"
        session = await self._get_session()
        try:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                if data.get("code") == 0:
                    return data.get("data")
                # Token might be expired, retry once
                if data.get("code") == 10000:
                    self._token = ""
                    token = await self._ensure_token()
                    if not token:
                        return None
                    sign_data = self._sign(path, query, token)
                    headers = self._headers(sign_data)
                    async with session.get(url, headers=headers) as resp2:
                        data2 = await resp2.json()
                        if data2.get("code") == 0:
                            return data2.get("data")
                logger.warning(
                    f"[SklandWiki] API error: {path} {data.get('code')}"
                )
        except Exception as e:
            logger.error(f"[SklandWiki] Request error: {path} {e}")
        return None

    # ---- public methods ----

    async def get_item_info(self, item_id: int) -> Optional[dict]:
        """Fetch wiki item detail by ID."""
        data = await self._get(WIKI_ITEM_INFO, f"id={item_id}")
        if data:
            return data.get("item")
        return None

    async def get_catalog(
        self, type_main_id: int = 1
    ) -> list[dict]:
        """Fetch wiki catalog with all items per subType.

        Returns the full catalog list. Each entry has typeSub with items[].
        One API call returns ALL items for all subTypes.
        Result is cached in memory for 1 hour.
        """
        if (
            self._catalog_cache
            and (time.time() - self._catalog_cache_time) < 3600
        ):
            return self._catalog_cache

        data = await self._get(
            WIKI_ITEM_CATALOG, f"typeMainId={type_main_id}"
        )
        if data:
            self._catalog_cache = data.get("catalog", [])
            self._catalog_cache_time = time.time()
            return self._catalog_cache
        return self._catalog_cache or []

    async def get_catalog_items(
        self,
        sub_type_names: set[str] | None = None,
    ) -> dict[str, list[dict]]:
        """Get all catalog items grouped by subType name.

        Args:
            sub_type_names: Filter. None = return all types.

        Returns:
            {"干员": [item, ...], "武器": [item, ...], ...}
            Each item has: itemId, name, brief{cover, subTypeList, ...}
        """
        catalog = await self.get_catalog()
        result: dict[str, list[dict]] = {}
        for cat in catalog:
            for sub in cat.get("typeSub", []):
                st_name = sub.get("name", "")
                if sub_type_names and st_name not in sub_type_names:
                    continue
                items = sub.get("items", [])
                if items:
                    result[st_name] = items
        return result


# Module-level singleton
wiki_client = SklandWikiClient()
