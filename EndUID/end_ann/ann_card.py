import io
import json
from typing import List, Union, Optional
from datetime import datetime
from pathlib import Path

from PIL import Image

from gsuid_core.logger import logger
from gsuid_core.utils.image.convert import convert_img

from ..utils.api.requests import end_api
from ..utils.path import ANN_CACHE_PATH
from ..utils.render_utils import (
    PLAYWRIGHT_AVAILABLE,
    render_html,
    get_image_b64_with_cache,
    image_to_base64,
)

# HTML 模板环境
from jinja2 import Environment, FileSystemLoader

TEMPLATE_PATH = Path(__file__).parent.parent / "templates"
end_templates = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))


def format_date(ts) -> str:
    """格式化时间戳为日期字符串"""
    if not ts:
        return "未知"
    try:
        if isinstance(ts, str):
            # 尝试解析 ISO 格式日期字符串
            for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]:
                try:
                    return datetime.strptime(ts, fmt).strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    continue
            return ts
        ts = int(ts)
        if ts <= 0:
            return "未知"
        # 处理毫秒和秒级时间戳
        if ts > 10000000000:
            ts = ts // 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "未知"


def format_date_short(ts) -> str:
    """格式化时间戳为短日期"""
    if not ts:
        return "未知"
    try:
        if isinstance(ts, str):
            for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]:
                try:
                    return datetime.strptime(ts, fmt).strftime("%m-%d")
                except ValueError:
                    continue
            return ts[:5] if len(ts) >= 5 else ts
        ts = int(ts)
        if ts <= 0:
            return "未知"
        if ts > 10000000000:
            ts = ts // 1000
        return datetime.fromtimestamp(ts).strftime("%m-%d")
    except Exception:
        return "未知"


async def ann_list_card() -> Union[bytes, str]:
    """生成公告列表卡片"""
    try:
        logger.debug("[End] 正在获取公告列表...")

        ann_list = await end_api.get_ann_list()
        if not ann_list:
            return "获取公告列表失败，请稍后重试"

        # 限制 18 条
        ann_list = ann_list[:18]

        # 处理公告数据
        items = []
        for i, ann in enumerate(ann_list):
            if i == 0:
                logger.debug(
                    f"[End] 首条公告原始数据 keys: {list(ann.keys())}, "
                    f"createdAtTs={ann.get('createdAtTs')}"
                )

            cover_url = ann.get("coverUrl", "")
            cover_b64 = ""
            if cover_url:
                cover_b64 = await get_image_b64_with_cache(
                    cover_url, ANN_CACHE_PATH, quality=60
                )

            user_avatar = ann.get("userAvatar", "")
            avatar_b64 = ""
            if user_avatar:
                avatar_b64 = await get_image_b64_with_cache(
                    user_avatar, ANN_CACHE_PATH, quality=70
                )

            raw_ts = ann.get("createdAtTs", 0)
            date_str = format_date_short(raw_ts)

            items.append({
                "id": ann.get("id", ""),
                "short_id": str(i + 1),
                "title": ann.get("title", "未知"),
                "date_str": date_str,
                "coverUrl": cover_url,
                "coverB64": cover_b64,
                "userName": ann.get("userName", ""),
                "userAvatar": avatar_b64,
                "userIpLocation": ann.get("userIpLocation", ""),
            })

        context = {
            "title": "终末地公告",
            "subtitle": "使用 end公告#序号 查看详情",
            "is_list": True,
            "items": items,
            "show_footer": False,
        }

        logger.debug(f"[End] 准备渲染公告列表, items: {len(items)}")
        img_bytes = await render_html(end_templates, "ann_card.html", context)

        if img_bytes:
            return img_bytes
        else:
            return "公告列表渲染失败"

    except Exception as e:
        logger.exception(f"[End] 公告列表生成失败: {e}")
        return f"公告列表生成失败: {e}"


async def ann_detail_card(
    ann_id: Union[int, str],
    is_check_time: bool = False
) -> Union[bytes, str, List[bytes]]:
    """生成公告详情卡片

    Args:
        ann_id: 公告 ID 或序号
        is_check_time: 是否检查时间（用于推送时过滤旧公告）

    Returns:
        图片字节或错误消息
    """
    try:
        logger.debug(f"[End] 正在获取公告详情: {ann_id}")

        # 如果是序号，转换为实际 ID
        actual_id = str(ann_id)
        if isinstance(ann_id, int) or (isinstance(ann_id, str) and ann_id.isdigit()):
            idx = int(ann_id)
            if 1 <= idx <= 18:
                # 可能是序号
                ann_list = await end_api.get_ann_list(is_cache=True)
                if ann_list and idx <= len(ann_list):
                    actual_id = ann_list[idx - 1].get("id", str(ann_id))
                    logger.debug(f"[End] 序号 {idx} 对应公告 ID: {actual_id}")

        detail = await end_api.get_ann_detail(actual_id)
        if not detail:
            return "未找到该公告"

        # 检查时间
        if is_check_time:
            created_ts = detail.get("createdAtTs", 0)
            if created_ts > 10000000000:
                created_ts = created_ts // 1000
            import time
            now_time = int(time.time())
            if created_ts < now_time - 86400:
                return "该公告已过期"

        # 处理图片
        images = detail.get("images", [])
        long_images = []
        normal_images = []

        for img in images:
            width = img.get("width", 0)
            height = img.get("height", 0)
            url = img.get("url", "")

            if width > 0 and height / width > 5:
                # 长图单独发送
                long_images.append(url)
            else:
                img_b64 = await get_image_b64_with_cache(
                    url, ANN_CACHE_PATH, quality=80
                )
                normal_images.append({
                    "url": url,
                    "urlB64": img_b64,
                    "width": width,
                    "height": height,
                })

        # 处理视频封面
        videos = detail.get("videos", [])
        video_covers = []
        for video in videos:
            cover_url = video.get("coverUrl", "")
            if cover_url:
                cover_b64 = await get_image_b64_with_cache(
                    cover_url, ANN_CACHE_PATH, quality=75
                )
                video_covers.append({
                    "coverUrl": cover_url,
                    "coverB64": cover_b64,
                })

        # 用户头像
        user_avatar = detail.get("userAvatar", "")
        avatar_b64 = ""
        if user_avatar:
            avatar_b64 = await get_image_b64_with_cache(
                user_avatar, ANN_CACHE_PATH, quality=70
            )

        context = {
            "title": detail.get("title", "公告详情"),
            "post_time": format_date(detail.get("createdAtTs", 0)),
            "user_name": detail.get("userName", "终末地"),
            "user_avatar": avatar_b64,
            "is_list": False,
            "images": normal_images,
            "videos": video_covers,
            "text_content": detail.get("textContent", []),
            "show_footer": False,
        }

        logger.debug(f"[End] 准备渲染公告详情, images: {len(normal_images)}")
        img_bytes = await render_html(end_templates, "ann_card.html", context)

        result_images = []

        # 处理长图
        if long_images:
            from ..utils.image import pic_download_from_url

            logger.info(f"[End] 检测到 {len(long_images)} 张超长图片，将单独发送")
            for img_url in long_images:
                try:
                    img = await pic_download_from_url(ANN_CACHE_PATH, img_url)
                    img_bytes_long = await convert_img(img)
                    result_images.append(img_bytes_long)
                except Exception as e:
                    logger.warning(f"[End] 下载超长图片失败: {img_url}, {e}")

        if img_bytes:
            if result_images:
                result_images = [img_bytes] + result_images
                return result_images
            return img_bytes
        else:
            return "公告详情渲染失败"

    except Exception as e:
        logger.exception(f"[End] 公告详情生成失败: {e}")
        return f"公告详情生成失败: {e}"
