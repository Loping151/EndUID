from gsuid_core.status.plugin_status import register_status

from ..utils.image import get_ICON
from ..utils.database.models import EndUser
from ..utils.status_store import get_today_counts, get_yesterday_counts


async def get_sign_num():
    return get_today_counts()["success"]


async def get_yesterday_sign_num():
    return get_yesterday_counts()["success"]


async def get_user_num():
    datas = await EndUser.get_all_data()
    return len(datas)


register_status(
    get_ICON(),
    "EndUID",
    {
        "签到人数": get_sign_num,
        "昨日签到": get_yesterday_sign_num,
        "登录用户数量": get_user_num,
    },
)