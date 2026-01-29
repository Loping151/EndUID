from pathlib import Path

from PIL import Image

ICON = Path(__file__).parent.parent.parent / "ICON.png"


def get_ICON():
    return Image.open(ICON)

async def pic_download_from_url(
    path: Path,
    pic_url: str,
) -> Image.Image:
    path.mkdir(parents=True, exist_ok=True)

    name = pic_url.split("/")[-1]
    _path = path / name
    if not _path.exists():
        from gsuid_core.utils.download_resource.download_file import download

        await download(pic_url, path, name, tag="[End]")

    return Image.open(_path).convert("RGBA")
