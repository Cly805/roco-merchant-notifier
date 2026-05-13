# 🛒 洛克王国世界：远行商人自动提醒助手

基于 GitHub Actions 的轻量自动化工具，监控《洛克王国世界》"远行商人"刷新状态，自动截图推送到手机。

> 原作者：[ALLCAPS-Droid/roco-merchant-notifier](https://github.com/ALLCAPS-Droid/roco-merchant-notifier)

## ✨ 特性

- 自动抓取远行商人刷新数据
- Jinja2 + Playwright 完美渲染截图
- ImgBB 图床自动上传
- 双通道推送：Android (NotifyMe) / iOS (Bark)
- GitHub Actions 定时运行，无需服务器

## 🚀 快速上手（3 分钟）

### 1. Fork 本仓库

点击右上角 **Fork** 按钮，复制到你自己的账号下。

### 2. 获取 API Key

| Key | 用途 | 获取方式 |
|-----|------|----------|
| `ROCOM_API_KEY` | 游戏数据接口 | 测试 key: `sk-ff14f964051a5c966564e29b5bd3a768` |
| `IMGBB_KEY` | 图片上传 | 注册 https://api.imgbb.com/ → 登录后页面显示 |

> ROCOM_API_KEY 来自 [Entropy-Increase-Team/astrbot_plugin_rocom](https://github.com/Entropy-Increase-Team/astrbot_plugin_rocom)

### 3. 获取推送 Key（二选一）

**📱 Android → NotifyMe**
1. 下载 App：https://notifyme.wzn556.top/download.html （直接下载 APK）
2. 安装后**先选择推送类型**，UUID 会显示在主界面
3. 复制 UUID（类似 `JEVUq3N4L96emrYVzzdkQe`）

**🍎 iOS → Bark**
- App Store 安装 Bark，App 内复制 Key

### 4. 配置 GitHub Secrets

进入你的仓库 → **Settings** → **Secrets and variables** → **Actions**，添加以下 Secrets：

| Secret 名称 | 必填 | 说明 |
|-------------|:---:|------|
| `ROCOM_API_KEY` | ✅ | 游戏数据 Key |
| `IMGBB_KEY` | ✅ | 图床 Key |
| `NOTIFYME_UUID` | 选填 | Android 推送 UUID |
| `BARK_KEY` | 选填 | iOS 推送 Key |

> 至少填一个推送 Key，没填的通道自动跳过。

### 5. 开启 Actions

进入 **Actions** 选项卡 → 点击 "I understand my workflows, go ahead and enable them"。

手动触发测试：Actions → 远行商人监控 → Run workflow。

## ⏰ 运行时间

北京时间每天 **08:05 / 12:05 / 16:05 / 20:05** 自动运行，对应游戏内四轮商人刷新。

## 🛠️ 技术栈

- Python 3.11 + Requests + Jinja2 + Playwright
- GitHub Actions (Ubuntu)
- ImgBB API / NotifyMe / Bark

## ⚠️ 免责声明

仅供学习交流使用，数据来源于第三方社区。接口稳定性不作保证，请勿商用。
