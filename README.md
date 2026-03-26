# EndUID

<p align="center">
  <a href="https://github.com/Loping151/EndUID"><img src="./ICON.png" width="256" height="256" alt="EndUID"></a>
<h1 align = "center">EndUID</h1>

## 说明

该去拉电线了

安装方式：

首先参考核心安装：https://docs.sayu-bot.com/

**需要安装额外依赖 [Node.js](https://nodejs.org/)。**

**建议安装 `playwright`，用于渲染公告、wiki图等功能。** 插件启动时会自动检测并安装 chromium 浏览器。如果自动安装失败，请手动执行：
```bash
# Linux/Mac
source .venv/bin/activate && uv pip install playwright && uv run playwright install chromium
# Windows
.venv\Scripts\activate; uv pip install playwright; uv run playwright install chromium
```

```bash
cd gsuid_core/gsuid_core/plugins
git clone https://github.com/Loping151/EndUID
```

登录方式：

可以认为仅支持森空岛扫码登录。因为我不管，都给我去下载森空岛。

催更/反馈/Bug/建议：与 [XWUID](https://github.com/Loping151/XutheringWavesUID) 首页的同一个群吧，不想再建群了。Issue亦会看。

## 丨其他

+ 本项目仅供学习使用，请勿用于商业用途。使用本插件视为同意提供用户凭据，用户凭据仅用于查询游戏数据。使用本插件造成的任何数据滥用行为与作者无关。

+ [GPL-3.0 License](https://github.com/Loping151/EndUID/blob/main/LICENSE)


## 致谢
- [arknights-plugin](https://github.com/gxy12345/arknights-plugin)
- [endfield-gacha](https://github.com/bhaoo/endfield-gacha) — Endfield 抽卡记录 API 参考
- Potentially 合作的攻略组。？