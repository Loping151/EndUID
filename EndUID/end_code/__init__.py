import re
import json
import time
import urllib.parse

import httpx

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

sv_end_code = SV("终末地兑换码")

invalid_code_list = ()

url = "https://a.4399.cn/endfield/tools/codes"


@sv_end_code.on_fullmatch(("code", "兑换码", "兌換碼"))
async def get_code_func(bot: Bot, ev: Event):
    code_list = await get_code_list()
    if not code_list:
        return await bot.send("[获取兑换码失败] 请稍后再试")

    now_ms = int(time.time() * 1000)
    msgs = []
    for item in code_list:
        code = item.get("code", "")
        if not code or code in invalid_code_list:
            continue
        e_time = item.get("e_time") or 0
        if e_time and e_time < now_ms:
            continue
        award = _strip_html(urllib.parse.unquote(item.get("award", "")))
        desc = item.get("desc", "")
        msg = [f"兑换码: {code}", f"奖励: {award}"]
        if desc:
            msg.append(desc)
        msgs.append("\n".join(msg))

    if not msgs:
        return await bot.send("暂无可用兑换码")

    await bot.send(msgs)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return text.strip()


async def get_code_list():
    try:
        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
            res = await client.get(
                url,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
        m = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>',
            res.text,
            re.DOTALL,
        )
        if not m:
            logger.error("[获取兑换码失败] __NEXT_DATA__ 未找到")
            return None
        data = json.loads(m.group(1))
        info_data = data.get("props", {}).get("pageProps", {}).get("infoData", [])
        for block in info_data:
            opts = block.get("options", {}) if isinstance(block, dict) else {}
            code_block = opts.get("Code") if isinstance(opts, dict) else None
            if code_block and "codes" in code_block:
                logger.debug(
                    f"[获取兑换码] url:{url}, codeList:{code_block.get('codes', [])}"
                )
                return code_block.get("codes", [])
        logger.error("[获取兑换码失败] infoData 中未找到 Code 块")
        return None
    except Exception as e:
        logger.exception("[获取兑换码失败] ", e)
        return None
