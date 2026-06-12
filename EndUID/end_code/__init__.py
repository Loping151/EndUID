import json
import time
from datetime import datetime

import httpx

from gsuid_core.sv import SV
from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event

sv_end_code = SV("终末地兑换码")

url = "https://newsimg.5054399.com/comm/mlcxqcommon/static/wap/js/data_171.js?{}&callback=?&_={}"
request_headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Referer": "https://www.4399.com/",
    "Accept": "*/*",
}


@sv_end_code.on_fullmatch(
    ("code", "兑换码", "兌換碼"),
    to_ai="""查询终末地（明日方舟：终末地）当前有效兑换码列表。

当用户问「终末地兑换码 / end 兑换码 / 终末地 前瞻兑换码 / 有没有兑换码」时调用。
不需要绑定 UID，结果是公开的兑换码 + 奖励 + 有效期。

Args:
    text: 无需参数。
""",
)
async def get_code_func(bot: Bot, ev: Event):
    code_list = await get_code_list()
    if not code_list:
        return await bot.send("[获取兑换码失败] 请稍后再试")

    msgs = []
    for code in code_list:
        is_fail = code.get("is_fail", "0")
        if is_fail == "1":
            continue
        order = code.get("order", "")
        if not order:
            continue
        reward = code.get("reward", "")
        label = code.get("label", "")
        msg = [f"兑换码: {order}", f"奖励: {reward}", label]
        msgs.append("\n".join(msg))

    await bot.send(msgs)


async def get_code_list():
    try:
        now = datetime.now()
        time_string = f"{now.year - 1900}{now.month - 1}{now.day}{now.hour}{now.minute}"
        now_time = int(time.time() * 1000)
        new_url = url.format(time_string, now_time)
        async with httpx.AsyncClient(timeout=None) as client:
            res = await client.get(new_url, headers=request_headers, timeout=10)
            res.raise_for_status()
            json_data = res.text.split("=", 1)[1].strip().rstrip(";")
            logger.debug(f"[ENDUID·获取兑换码] url:{new_url}, codeList:{json_data}")
            return json.loads(json_data)

    except Exception as e:
        logger.exception("[ENDUID·获取兑换码失败] ", e)
        return
