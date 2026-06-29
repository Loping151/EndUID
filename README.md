# EndUID

<p align="center">
  <a href="https://github.com/Loping151/EndUID"><img src="./ICON.png" width="256" height="256" alt="EndUID"></a>
<h1 align = "center">EndUID</h1>

## 说明

该去拉电线了

安装方式：

首先参考核心安装：https://docs.sayu-bot.com/

**渲染方案二选一：**

**方案 A：本地 `playwright`**（自带浏览器）
```bash
# Linux/Mac
source .venv/bin/activate && uv pip install playwright && uv run playwright install chromium
# Windows
.venv\Scripts\activate; uv pip install playwright; uv run playwright install chromium
```

**方案 B：外置渲染服务**（无需本地浏览器）
自建外置渲染：[RemoteRender](https://github.com/Loping151/RemoteRender)。
在配置中开启 `RemoteRenderEnable` 并填写 `RemoteRenderUrl`（默认 `http://127.0.0.1:3000/render`），所有 HTML→图渲染会走外置服务，本地无需安装 playwright/chromium。日历模块也已重写为纯 HTTP 直连，不再依赖浏览器；其他指令（公告/抽卡/wiki/基建/日常等）只要外置渲染服务可达即可。

```bash
cd gsuid_core/gsuid_core/plugins
git clone https://github.com/Loping151/EndUID
```

登录方式：

支持森空岛扫码登录。链接登陆需自行配置网络。

催更/反馈/Bug/建议：群号 885617919（注意入群问题的答案仓库是 [XutheringWavesUID](https://github.com/Loping151/XutheringWavesUID)），共用一个，不想再建群了。Issue亦会看。如果森空岛出了新的可查询内容，并且你希望通过EndUID查看，请告诉我。

## 丨其他

+ 本项目仅供学习使用，请勿用于商业用途。使用本插件视为同意提供用户凭据，用户凭据仅用于查询游戏数据。使用本插件造成的任何数据滥用行为与作者无关。

+ [GPL-3.0 License](https://github.com/Loping151/EndUID/blob/main/LICENSE)


## 致谢
- [arknights-plugin](https://github.com/gxy12345/arknights-plugin)
- [endfield-gacha](https://github.com/bhaoo/endfield-gacha) — Endfield 抽卡记录 API 参考
- Potentially 攻略组