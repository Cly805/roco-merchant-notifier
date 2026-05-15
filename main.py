import os
import requests
import asyncio
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright

# 加载 .env 文件
load_dotenv()

# ================= 1. 配置区域 =================
ROCOM_API_KEY = os.environ.get("ROCOM_API_KEY")
IMGBB_KEY = os.environ.get("IMGBB_KEY")
NOTIFYME_UUIDS = [u.strip() for u in os.environ.get("NOTIFYME_UUID", "").split(",") if u.strip()]
BARK_KEYS = [k.strip() for k in os.environ.get("BARK_KEY", "").split(",") if k.strip()]
CHROMIUM_PATH = os.environ.get("CHROMIUM_PATH")  # 可选：自定义 Chromium 路径

GAME_API_URL = "https://wegame.shallow.ink/api/v1/games/rocom/merchant/info"
NOTIFYME_SERVER = "https://notifyme-server.wzn556.top/api/send"
ASSETS_DIR = os.path.abspath("assets/yuanxing-shangren")
HTML_TEMPLATE_FILE = "index.html"
TEMP_RENDER_FILE = "temp_render.html"

# ================= 2. 时间与数据处理逻辑 =================

def get_beijing_time():
    """获取精准的北京时间"""
    return datetime.now(timezone(timedelta(hours=8)))


def format_timestamp(ts_ms):
    """格式化时间戳为 HH:mm"""
    if not ts_ms:
        return "--:--"
    dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone(timedelta(hours=8)))
    return dt.strftime("%H:%M")


def get_round_info():
    """计算当前远行商人的轮次与倒计时"""
    now = get_beijing_time()
    start_time = now.replace(hour=8, minute=0, second=0, microsecond=0)

    if now < start_time:
        return {"current": "未开放", "total": 4, "countdown": "尚未开市"}

    delta_seconds = int((now - start_time).total_seconds())
    round_index = (delta_seconds // (4 * 3600)) + 1

    if round_index > 4:
        return {"current": 4, "total": 4, "countdown": "今日已收市"}

    round_end = start_time + timedelta(hours=round_index * 4)
    remaining = round_end - now
    hours, rem = divmod(int(remaining.total_seconds()), 3600)
    minutes, _ = divmod(rem, 60)

    countdown_str = f"{hours}小时{minutes}分钟" if hours > 0 else f"{minutes}分钟"

    return {"current": round_index, "total": 4, "countdown": countdown_str}


def get_expected_round_start_ms():
    """
    计算当前轮次预期开始时间的毫秒时间戳。
    用于校验 API 返回数据是否属于当前轮次。
    """
    now = get_beijing_time()
    day_start = now.replace(hour=8, minute=0, second=0, microsecond=0)

    if now < day_start:
        return None  # 未开市

    delta_seconds = int((now - day_start).total_seconds())
    round_index = delta_seconds // (4 * 3600)  # 0-indexed: 0=8:00, 1=12:00, 2=16:00, 3=20:00

    if round_index > 3:
        return None  # 已收市

    round_start = day_start + timedelta(hours=round_index * 4)
    return int(round_start.timestamp() * 1000)


def validate_round_data(raw_data, tolerance_minutes=20):
    """
    校验 API 返回数据是否属于当前轮次。
    检查至少有一个商品的 start_time 落在当前轮次预期开始时间的 ±tolerance 范围内。
    返回 True 表示数据有效，False 表示可能是缓存旧数据。
    """
    expected_start_ms = get_expected_round_start_ms()
    if expected_start_ms is None:
        # 未开市或已收市，不需要验证
        return True

    tolerance_ms = tolerance_minutes * 60 * 1000

    activities = raw_data.get("merchantActivities") or raw_data.get("merchant_activities") or []

    for activity in activities:
        for bucket_key in ("get_props", "get_extra_props", "get_pets"):
            items = activity.get(bucket_key) or []
            for item in items:
                if not isinstance(item, dict):
                    continue
                s_time = item.get("start_time") or activity.get("start_time")
                if s_time:
                    item_start_ms = int(s_time)
                    # 商品开始时间在预期轮次开始时间的 ±tolerance 范围内
                    if abs(item_start_ms - expected_start_ms) < tolerance_ms:
                        return True

    print(f"⚠️ 轮次校验失败: 未找到属于当前轮次（预期开始 {expected_start_ms}）的商品")
    return False


def fetch_merchant_data(max_retries=8, retry_delay=15, stale_fallback=False):
    """
    获取远行商人数据，带破缓存和轮次校验重试。
    解决第三方 API 缓存延迟导致「落后一轮」的问题。

    max_retries: 最大重试次数 (默认 8 次)
    retry_delay: 重试间隔秒数 (默认 15 秒)，总等待最长约 120 秒
    stale_fallback: 重试耗尽后是否降级使用旧数据 (默认 False，不发旧数据)
    """
    for attempt in range(1, max_retries + 1):
        # cache-busting: 加时间戳参数破 CDN/代理缓存
        cache_buster = int(time.time() * 1000)
        url = f"{GAME_API_URL}?_t={cache_buster}"

        try:
            resp = requests.get(url, headers={"X-API-Key": ROCOM_API_KEY}, timeout=30)
            resp.raise_for_status()
            json_data = resp.json()

            if json_data.get("code") != 0:
                err_msg = json_data.get("message", "API 返回错误")
                print(f"❌ API 错误 (尝试 {attempt}/{max_retries}): {err_msg}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                return None, err_msg

            raw_data = json_data.get("data", {})

            # 轮次校验：确保数据属于当前轮次
            if validate_round_data(raw_data):
                print(f"✅ 数据获取成功，通过轮次校验 (尝试 {attempt}/{max_retries})")
                return raw_data, None
            else:
                elapsed = attempt * retry_delay
                print(f"⚠️ 数据可能是旧轮次缓存 (尝试 {attempt}/{max_retries}，已等待 ~{elapsed}s)")
                if attempt < max_retries:
                    print(f"   等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                else:
                    total_wait = max_retries * retry_delay
                    if stale_fallback:
                        print(f"⚠️ 已达最大重试次数 (~{total_wait}s)，降级使用当前数据（可能为旧轮次）")
                        return raw_data, None
                    else:
                        print(f"❌ 已达最大重试次数 (~{total_wait}s)，数据仍为旧轮次，放弃推送")
                        return None, "数据暂未更新（第三方 API 缓存延迟），请稍后重试"

        except Exception as e:
            print(f"❌ 请求异常 (尝试 {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(retry_delay)
                continue
            return None, f"请求异常: {e}"

    return None, "未知错误"


def process_data_for_template(data):
    if not data:
        return {}

    now_ms = int(get_beijing_time().timestamp() * 1000)
    round_info = get_round_info()

    activities = data.get("merchantActivities") or data.get("merchant_activities") or []
    activity = activities[0] if activities else {}

    # 获取三种类型的商品
    buckets = [
        ("道具", activity.get("get_props") or []),
        ("额外道具", activity.get("get_extra_props") or []),
        ("精灵", activity.get("get_pets") or []),
    ]

    # 匹配商品元数据字典 (用于获取价格和限购次数)
    random_goods = data.get("random_goods") if isinstance(data.get("random_goods"), list) else []
    goods_meta_by_name = {
        str(item.get("goods_name", "") or item.get("name", "")).strip(): item
        for item in random_goods
        if isinstance(item, dict) and str(item.get("goods_name", "") or item.get("name", "")).strip()
    }

    all_products = []
    active_products = []

    for category, items in buckets:
        for item in items:
            if not isinstance(item, dict):
                continue

            goods_meta = goods_meta_by_name.get(str(item.get("name", "")).strip(), {})

            s_time = item.get("start_time")
            e_time = item.get("end_time")

            # 兜底继承大活动时间
            if s_time is None:
                s_time = activity.get("start_time")
            if e_time is None:
                e_time = activity.get("end_time")

            start_ms = int(s_time) if s_time else None
            end_ms = int(e_time) if e_time else None

            is_active = True
            if start_ms is not None and end_ms is not None:
                is_active = start_ms <= now_ms < end_ms

            status_label = "当前轮次"
            if start_ms is not None and now_ms < start_ms:
                status_label = "未开始"
            elif end_ms is not None and now_ms >= end_ms:
                status_label = "已结束"

            # 时间标签格式化
            start_str = format_timestamp(start_ms)
            end_str = format_timestamp(end_ms)
            if start_str[:5] == end_str[:5] and start_str != "--:--":
                time_label = f"{start_str} - {end_str[6:]}" if len(end_str) > 6 else f"{start_str} - {end_str}"
            else:
                time_label = f"{start_str} - {end_str}"

            product = {
                "name": item.get("name", "未知商品"),
                "image": item.get("icon_url", ""),
                "time_label": time_label,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "is_active": is_active,
                "status_label": status_label,
                "price": item.get("price") if item.get("price") not in (None, "") else goods_meta.get("price"),
                "buy_limit_num": item.get("buy_limit_num") if item.get("buy_limit_num") not in (None, "") else goods_meta.get("buy_limit_num"),
            }

            all_products.append(product)
            if is_active:
                active_products.append(product)

    # 历史记录分组逻辑
    today = datetime.fromtimestamp(now_ms / 1000, tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    grouped = {}

    for product in all_products:
        if product["is_active"]:
            continue
        start_ms = product["start_ms"]
        if not start_ms:
            continue

        start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone(timedelta(hours=8)))
        if start_dt.strftime("%Y-%m-%d") != today:
            continue

        key = f"{start_ms}-{product['end_ms'] or ''}"
        if key not in grouped:
            grouped[key] = {
                "time_label": product["time_label"] or "--:--",
                "status_label": product["status_label"] or "其他时段",
                "sort": start_ms,
                "products": [],
            }
        group = grouped[key]
        names = {p["name"] for p in group["products"]}
        # 每段最多展示5个不重复商品
        if product["name"] not in names and len(group["products"]) < 5:
            group["products"].append(product)

    history_groups = [
        {k: v for k, v in g.items() if k != "sort"}
        for g in sorted(grouped.values(), key=lambda x: x["sort"])
        if g["products"]
    ]

    return {
        "title": activity.get("name", "远行商人"),
        "subtitle": activity.get("start_date", "每日 08:00 / 12:00 / 16:00 / 20:00 刷新"),
        "product_count": len(active_products),
        "round_info": round_info,
        "products": active_products,
        "history_groups": history_groups,
        "_res_path": "",
        "background": "img/bg.C8CUoi7I.jpg",
        "titleIcon": True,
    }


# ================= 3. 图像渲染与上传 =================

async def render_to_image(processed_data):
    """渲染 HTML 并精准切割截图"""
    if not processed_data or processed_data["product_count"] == 0:
        print("当前无活跃商品，跳过渲染")
        return None

    screenshot_file = "merchant_render.jpg"
    temp_html_path = os.path.join(ASSETS_DIR, TEMP_RENDER_FILE)

    try:
        env = Environment(loader=FileSystemLoader(ASSETS_DIR))
        template = env.get_template(HTML_TEMPLATE_FILE)
        rendered_html = template.render(processed_data)

        with open(temp_html_path, "w", encoding="utf-8") as f:
            f.write(rendered_html)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                executable_path=CHROMIUM_PATH or None,
            )
            page = await browser.new_page()

            await page.set_viewport_size({"width": 900, "height": 1600})
            await page.goto(f"file://{temp_html_path}")

            await page.evaluate("document.fonts.ready")
            await page.wait_for_load_state("networkidle")

            data_region = page.locator(".merchant-page")
            await data_region.screenshot(path=screenshot_file, type="jpeg", quality=90)

            await browser.close()
            print(f"✅ 图片渲染成功: {screenshot_file}")
            return screenshot_file

    except Exception as e:
        print(f"❌ 渲染图片失败: {e}")
        return None
    finally:
        if os.path.exists(temp_html_path):
            os.remove(temp_html_path)


async def upload_to_imgbb(image_path):
    """上传到 ImgBB 图床"""
    if not image_path or not IMGBB_KEY:
        return None
    try:
        with open(image_path, "rb") as f:
            res = requests.post(
                "https://api.imgbb.com/1/upload",
                data={"key": IMGBB_KEY},
                files={"image": f},
                timeout=30,
            )
            json_data = res.json()
            if json_data.get("status") == 200:
                print("✅ 图床上传成功")
                return json_data["data"]["url"]
            else:
                print(f"❌ 图床上传失败: {json_data.get('error', {}).get('message')}")
                return None
    except Exception as e:
        print(f"❌ 图床请求异常: {e}")
        return None


# ================= 4. 推送分发 =================

def push_all(title, body, markdown, image_url):
    """执行双通道推送，支持多人"""
    for uuid in NOTIFYME_UUIDS:
        payload = {
            "data": {
                "uuid": uuid,
                "ttl": 86400,
                "priority": "high",
                "data": {
                    "title": title,
                    "body": body,
                    "group": "洛克王国",
                    "bigText": True,
                    "record": 1,
                    "markdown": f"{markdown}\n\n![render]({image_url})" if image_url else markdown,
                },
            }
        }
        try:
            requests.post(NOTIFYME_SERVER, json=payload, timeout=10)
            print(f"✅ NotifyMe 推送已发送 → {uuid[:8]}...")
        except:
            print(f"⚠️ NotifyMe 推送失败 → {uuid[:8]}...")

    for key in BARK_KEYS:
        try:
            requests.post(
                f"https://api.day.app/{key}",
                data={
                    "title": title,
                    "body": body,
                    "group": "洛克王国",
                    "image": image_url,
                    "isArchive": 1,
                },
                timeout=10,
            )
            print(f"✅ Bark 推送已发送 → {key[:8]}...")
        except:
            print(f"⚠️ Bark 推送失败 → {key[:8]}...")


# ================= 5. 主入口 =================

async def main():
    # 使用带重试和轮次校验的 fetch，自动破缓存
    # 8 次重试 × 15 秒 = 最多等待 120 秒，给第三方 API 缓存足够的刷新时间
    # stale_fallback=False: 超时后不发旧数据，推警告通知
    raw_data, err = fetch_merchant_data(max_retries=8, retry_delay=15, stale_fallback=False)

    if err or not raw_data:
        push_all("⚠️ 监控异常", err or "无法获取数据", "无法获取数据", None)
        return

    processed = process_data_for_template(raw_data)
    item_names = [p["name"] for p in processed["products"]]
    push_body = f"当前售卖: {'、'.join(item_names)}" if item_names else "当前暂无商品"

    local_img = await render_to_image(processed)
    img_url = await upload_to_imgbb(local_img)

    push_all("📢 远行商人已刷新", push_body, "### 🛒 商人刷新详情", img_url)


if __name__ == "__main__":
    asyncio.run(main())
