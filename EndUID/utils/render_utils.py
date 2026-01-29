import base64
import asyncio
import time
import re
import logging
from typing import Union, Optional
from pathlib import Path

import httpx

from gsuid_core.logger import logger
from gsuid_core.config import core_config, CONFIG_DEFAULT
from gsuid_core.app_life import app as fastapi_app
from fastapi.staticfiles import StaticFiles
from .path import TEMP_PATH
from ..end_config import EndConfig

logging.getLogger("uvicorn.access").addFilter(
    lambda record: "/end/fonts" not in record.getMessage()
)

TEMPLATES_ABS_PATH = Path(__file__).parent.parent / "templates"

class CORSStaticFiles(StaticFiles):
    """Custom StaticFiles class to add CORS headers only for served files."""
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, HEAD"
        return response

def _import_playwright():
    try:
        from playwright.async_api import async_playwright
        return async_playwright
    except ImportError:
        if not EndConfig.get_config("RemoteRenderEnable").data:
            logger.warning("[End] 未安装 playwright，无法使用渲染公告、wiki图等功能。")
            logger.warning("[End] 可选择配置外置渲染方法！")
            logger.info("[End] 安装方法 Linux/Mac: 在当前目录下执行 source .venv/bin/activate && uv pip install playwright && uv run playwright install chromium")
            logger.info("[End] 安装方法 Windows: 在当前目录下执行 .venv\\Scripts\\activate; uv pip install playwright; uv run playwright install chromium")
        return None


async_playwright = _import_playwright()
PLAYWRIGHT_AVAILABLE = async_playwright is not None

_playwright = None
_browser = None
_browser_lock = asyncio.Lock()
_browser_uses = 0
_last_used = 0.0
_active_contexts = 0

_MAX_BROWSER_USES = 1000
_BROWSER_IDLE_TTL = 3600

_FONT_CSS_NAME = "fonts.css"
_FONTS_DIR = TEMP_PATH / "fonts"


def _mount_fonts() -> None:
    try:
        for route in fastapi_app.routes:
            if getattr(route, "path", None) == "/end/fonts":
                return
        if _FONTS_DIR.exists():
            fastapi_app.mount(
                "/end/fonts",
                CORSStaticFiles(directory=_FONTS_DIR),
                name="wwuid_fonts",
            )
        logger.debug("[End] 已挂载字体静态路由 (CORS Enabled)")
    except Exception as e:
        logger.warning(f"[End] 挂载字体静态路由失败: {e}")


def _get_local_base_url() -> str:
    host = core_config.get_config("HOST") or CONFIG_DEFAULT["HOST"]
    port = core_config.get_config("PORT") or CONFIG_DEFAULT["PORT"]
    if host in ("0.0.0.0", "0.0.0.0:"):
        host = "127.0.0.1"
    return f"http://{host}:{port}"


_mount_fonts()


async def _ensure_browser():
    """Get a reusable browser instance; restart periodically to bound memory."""
    global _playwright, _browser, _browser_uses, _last_used, _active_contexts

    if not PLAYWRIGHT_AVAILABLE or async_playwright is None:
        return None

    async with _browser_lock:
        now = time.monotonic()

        if _browser is not None and not _browser.is_connected():
            try:
                await _browser.close()
            except Exception:
                pass
            _browser = None

        need_restart = (
            _browser is None
            or _browser_uses >= _MAX_BROWSER_USES
            or (_last_used > 0 and now - _last_used > _BROWSER_IDLE_TTL)
        )

        if need_restart and _browser is not None and _active_contexts > 0:
            need_restart = False

        if need_restart:
            if _browser is not None:
                try:
                    await _browser.close()
                except Exception:
                    pass
                _browser = None

            if _playwright is None:
                _playwright = await async_playwright().start()

            _browser = await _playwright.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            _browser_uses = 0

        _last_used = now
        return _browser


async def _render_via_remote(html_content: str, remote_url: str) -> Optional[bytes]:
    """使用外置渲染服务渲染 HTML"""
    start_time = time.time()
    try:
        logger.debug(f"[End] 尝试使用外置渲染服务: {remote_url}")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                remote_url,
                json={"html": html_content},
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                image_data = response.content
                elapsed_time = time.time() - start_time
                logger.info(f"[End] 外置渲染成功，耗时: {elapsed_time:.2f}s，图片大小: {len(image_data)} bytes")
                return image_data
            else:
                logger.warning(f"[End] 外置渲染失败，状态码: {response.status_code}, 错误: {response.text}")
                return None
    except httpx.TimeoutException:
        elapsed_time = time.time() - start_time
        logger.warning(f"[End] 外置渲染超时 ({elapsed_time:.2f}s)，将回退到本地渲染")
        return None
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.warning(f"[End] 外置渲染异常 ({elapsed_time:.2f}s): {e}，将回退到本地渲染")
        return None


async def render_html(end_templates, template_name: str, context: dict) -> Optional[bytes]:
    global _browser_uses, _last_used, _active_contexts

    try:
        logger.debug(f"[End] HTML渲染开始: {template_name}")

        template = end_templates.get_template(template_name)

        remote_render_enable = EndConfig.get_config("RemoteRenderEnable").data
        remote_url = EndConfig.get_config("RemoteRenderUrl").data if remote_render_enable else None

        if remote_render_enable and remote_url:
            try:
                font_css_url = EndConfig.get_config("FontCssUrl").data
                context["font_css_url"] = font_css_url
                html_content = template.render(**context)
                logger.debug(f"[End] 使用在线字体渲染 HTML: {template_name}")
                logger.debug(f"[End] 外置渲染已启用，尝试使用: {remote_url}")
                remote_result = await _render_via_remote(html_content, remote_url)
                if remote_result is not None:
                    return remote_result

                logger.info("[End] 外置渲染失败，回退到本地渲染")
            except Exception as e:
                logger.warning(f"[End] 外置渲染异常: {e}，回退到本地渲染")

        try:
            font_css_path = _FONTS_DIR / _FONT_CSS_NAME
            base_url = _get_local_base_url()

            if font_css_path.exists():
                context["font_css_url"] = f"{base_url}/end/fonts/{_FONT_CSS_NAME}"
            else:
                # 本地没有fonts.css时，使用配置的在线字体URL
                font_css_url = EndConfig.get_config("FontCssUrl").data
                context["font_css_url"] = font_css_url

            html_content = template.render(**context)
            logger.debug(f"[End] 使用本地字体渲染 HTML: {template_name}")
        except Exception as e:
            logger.error(f"[End] Template render failed: {e}")
            raise e

        # 本地渲染
        if not PLAYWRIGHT_AVAILABLE or async_playwright is None:
            logger.warning("[End] Playwright 未安装，无法渲染，将回退到 PIL 渲染（如有）")
            return None

        logger.debug(f"[End] 使用本地 Playwright 渲染")
        logger.debug(f"[End] async_playwright type: {type(async_playwright)}")

        font_css_path = _FONTS_DIR / _FONT_CSS_NAME
        if not font_css_path.exists():
            logger.warning("[End] fonts.css 不存在，继续使用原始字体链接。")

        local_start_time = time.time()
        try:
            logger.debug("[End] 获取复用浏览器实例...")
            browser = await _ensure_browser()
            if browser is None:
                return None

            context_obj = await browser.new_context(viewport={"width": 1200, "height": 1000})
            _active_contexts += 1
            try:
                page = await context_obj.new_page()
                logger.debug("[End] 加载HTML内容...")
                await page.set_content(html_content)

                logger.debug("[End] 正在计算容器尺寸...")
                container = page.locator(".container")
                await page.wait_for_selector(".container", timeout=2000)
                size = await container.evaluate(
                    """(el) => {
                        const rect = el.getBoundingClientRect();
                        const width = Math.ceil(Math.max(rect.width, el.scrollWidth));
                        const height = Math.ceil(Math.max(rect.height, el.scrollHeight));
                        return { width, height };
                    }"""
                )

                if size and size.get("width") and size.get("height"):
                    await page.set_viewport_size(
                        {
                            "width": max(1, int(size["width"])),
                            "height": max(1, int(size["height"])),
                        }
                    )
                    await page.wait_for_timeout(50)

                logger.debug("[End] 正在截图...")
                screenshot = await container.screenshot(type='jpeg', quality=90)
                local_elapsed_time = time.time() - local_start_time
                logger.info(f"[End] 本地渲染成功，耗时: {local_elapsed_time:.2f}s，图片大小: {len(screenshot)} bytes")
                return screenshot
            finally:
                try:
                    await context_obj.close()
                except Exception:
                    pass
                _active_contexts = max(0, _active_contexts - 1)
                _browser_uses += 1
                _last_used = time.monotonic()
        except Exception as e:
            logger.error(f"[End] Playwright execution failed: {e}")
            raise e

    except Exception as e:
        logger.error(f"[End] HTML渲染失败: {e}")
        return None


def image_to_base64(image_path: Union[str, Path]) -> str:
    if not isinstance(image_path, Path):
        image_path = Path(image_path)
    if not image_path.exists():
        return ""
    try:
        with open(image_path, "rb") as f:
            data = f.read()
        ext = image_path.suffix.lstrip(".").lower()
        if ext == "jpg":
            ext = "jpeg"
        return f"data:image/{ext};base64,{base64.b64encode(data).decode('utf-8')}"
    except Exception as e:
        logger.warning(f"[渲染工具] 图片转 base64 失败: {image_path}, {e}")
        return ""


def get_logo_b64() -> Optional[str]:
    try:
        logo_path = TEMP_PATH / "imgs" / "kurobbs.png"

        if not logo_path.exists():
            return None

        with open(logo_path, "rb") as f:
            data = f.read()
            return f"data:image/png;base64,{base64.b64encode(data).decode('utf-8')}"
    except Exception as e:
        logger.warning(f"[渲染工具] Logo loading failed: {e}")
        return None


def get_footer_b64(footer_type: str = "black") -> Optional[str]:
    try:
        from pathlib import Path

        current_file_path = Path(__file__).resolve()
        footer_path = current_file_path.parent / "texture2d" / f"footer_{footer_type}.png"

        if not footer_path.exists():
            if footer_type == "black":
                footer_path = current_file_path.parent / "texture2d" / "footer_white.png"
            else:
                footer_path = current_file_path.parent / "texture2d" / "footer_black.png"

        if not footer_path.exists():
            return None

        with open(footer_path, "rb") as f:
            data = f.read()
            return f"data:image/png;base64,{base64.b64encode(data).decode('utf-8')}"
    except Exception as e:
        logger.warning(f"[渲染工具] Footer loading failed: {e}")
        return None


async def get_image_b64_with_cache(url: str, cache_path: Path, quality = None) -> str:
    if not url:
        return ""

    try:
        from .image import pic_download_from_url
        from PIL import Image
        from io import BytesIO

        await pic_download_from_url(cache_path, url)

        filename = url.split("/")[-1]
        local_path = cache_path / filename

        # 如果 quality 为 None，不压缩，直接返回原始图片的 base64
        if quality is None:
            ext = local_path.suffix.lstrip(".").lower()
            if ext == "jpg":
                ext = "jpeg"
            with open(local_path, "rb") as f:
                data = f.read()
            b64_str = f"data:image/{ext};base64,{base64.b64encode(data).decode('utf-8')}"
            return b64_str

        img = Image.open(local_path)

        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
                img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        buffer = BytesIO()
        img.save(buffer, 'JPEG', quality=quality, optimize=True)
        buffer.seek(0)

        data = buffer.read()
        b64_str = f"data:image/jpeg;base64,{base64.b64encode(data).decode('utf-8')}"

        orig_size = local_path.stat().st_size
        compressed_size = len(data)
        compression_ratio = (1 - compressed_size / orig_size) * 100 if orig_size > 0 else 0
        logger.debug(f"[渲染工具] 图片压缩: {filename}, 原始: {orig_size} bytes, 压缩后: {compressed_size} bytes, 压缩率: {compression_ratio:.2f}%")

        return b64_str

    except Exception as e:
        logger.warning(f"[渲染工具] 获取图片 base64 失败: {url}, {e}")
        return ""
