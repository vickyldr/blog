#!/usr/bin/env python3
"""
小红书 MCP Server
用 Playwright 控制浏览器，支持：搜索 / 看帖 / 点赞 / 收藏 / 评论 / 发帖
"""

from pathlib import Path
from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright

STATE_FILE = Path(__file__).parent / "xhs_state.json"  # storage_state: cookies + localStorage
XHS_URL = "https://www.xiaohongshu.com"

mcp = FastMCP("小红书")

_pw = None
_browser = None
_ctx = None
_page = None


async def get_page():
    global _pw, _browser, _ctx, _page

    # 1. 已有打开的 page，直接复用（同一个 context，session 不变）
    if _page and not _page.is_closed():
        return _page

    # 2. context 还活着，只需在里面开新 page
    if _ctx:
        try:
            _page = await _ctx.new_page()
            return _page
        except Exception:
            pass

    # 3. 完全重建：playwright → browser → context → page
    if _pw is None:
        _pw = await async_playwright().start()

    _browser = await _pw.chromium.launch(
        headless=False,
        slow_mo=50,
        args=["--window-size=1920,1080"]
    )

    # storage_state 会同时恢复 cookies + localStorage + sessionStorage
    ctx_kwargs = dict(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
    )
    if STATE_FILE.exists():
        ctx_kwargs["storage_state"] = str(STATE_FILE)

    _ctx = await _browser.new_context(**ctx_kwargs)
    _page = await _ctx.new_page()

    try:
        cdp = await _ctx.new_cdp_session(_page)
        window_info = await cdp.send("Browser.getWindowForTarget")
        await cdp.send("Browser.setWindowBounds", {
            "windowId": window_info["windowId"],
            "bounds": {"windowState": "maximized"}
        })
    except Exception:
        pass

    return _page


async def check_login(page) -> bool:
    """检查当前页面是否有登录/扫码弹窗。"""
    return await page.evaluate("""
        () => {
            const text = document.body.innerText || '';
            return text.includes('扫码') || (text.includes('登录') && text.includes('二维码'));
        }
    """)


async def dom_click(page, text: str) -> bool:
    """用JavaScript直接在DOM上触发click，完全不依赖viewport位置。"""
    return await page.evaluate(f"""
        () => {{
            const result = document.evaluate(
                "//*[normalize-space(text())='{text}']",
                document, null,
                XPathResult.FIRST_ORDERED_NODE_TYPE, null
            );
            const el = result.singleNodeValue;
            if (el) {{ el.click(); return true; }}
            return false;
        }}
    """)


async def save_cookies():
    """保存完整的浏览器状态（cookies + localStorage + sessionStorage）。"""
    if _ctx:
        await _ctx.storage_state(path=str(STATE_FILE))


@mcp.tool()
async def xhs_login() -> str:
    """打开小红书网页，等你在浏览器里手动登录（扫码或账号密码）。登录完成后调用 xhs_save_login。"""
    page = await get_page()
    await page.goto(XHS_URL)
    return "浏览器已打开小红书，请手动登录。登录完成后调用 xhs_save_login 保存状态。"


@mcp.tool()
async def xhs_login_creator() -> str:
    """打开小红书创作者平台，等你在浏览器里登录。登录完成后调用 xhs_save_login。发帖前必须先调用这个。"""
    page = await get_page()
    await page.goto("https://creator.xiaohongshu.com")
    return "浏览器已打开创作者平台，请手动登录。登录完成后调用 xhs_save_login 保存状态。"


@mcp.tool()
async def xhs_save_login() -> str:
    """登录完成后调用，把登录状态（包括创作者平台）保存到本地，下次启动不用重新登录。"""
    await save_cookies()
    return f"登录状态已保存。State 文件路径：{STATE_FILE}  |  文件是否存在：{STATE_FILE.exists()}"


@mcp.tool()
async def xhs_search(keyword: str) -> str:
    """搜索小红书笔记，返回前10条结果。"""
    page = await get_page()
    await page.goto(f"{XHS_URL}/search_result?keyword={keyword}&source=web_explore_feed")
    await page.wait_for_load_state("networkidle", timeout=12000)
    await page.wait_for_timeout(1500)

    notes = await page.evaluate("""() => {
        const items = [...document.querySelectorAll('section.note-item')];
        return items.slice(0, 10).map(el => ({
            title: el.querySelector('.title span, [class*="title"]')?.innerText?.trim() || '',
            author: el.querySelector('.author .name, .name')?.innerText?.trim() || '',
            likes: el.querySelector('[class*="like"] [class*="count"], .like-wrapper .count')?.innerText?.trim() || '',
            url: el.querySelector('a')?.href || ''
        }));
    }""")

    if not notes:
        return f'没有找到关于"{keyword}"的结果，或者还没有登录（先调用 xhs_login）。'

    lines = [f'搜索"{keyword}"的结果：\n']
    for i, n in enumerate(notes, 1):
        lines.append(f"{i}. {n['title'] or '(无标题)'}")
        if n['author']:
            lines.append(f"   作者：{n['author']}")
        if n['likes']:
            lines.append(f"   点赞：{n['likes']}")
        if n['url']:
            lines.append(f"   链接：{n['url']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def xhs_get_note(url: str) -> str:
    """获取一篇小红书笔记的标题、正文、作者、点赞数和前5条评论。"""
    page = await get_page()
    state_status = f"[debug] State 文件：{STATE_FILE}  |  存在：{STATE_FILE.exists()}"

    await page.goto(url)
    await page.wait_for_load_state("networkidle", timeout=15000)
    await page.wait_for_timeout(3000)

    if await check_login(page):
        return f"页面要求登录，请调用 xhs_login 重新登录，登完调 xhs_save_login 保存。\n[debug] {state_status}"

    # 仅当页面没有帖子内容、且出现 App 跳转提示时，才认定为仅限App
    app_only = await page.evaluate("""
        () => {
            const body = document.body.innerText || '';
            const hasAppPrompt = body.includes('仅支持App查看') || body.includes('请在App内查看')
                || body.includes('Open in App') || document.querySelector('[class*="openApp"], [class*="open-app"]') !== null;
            const hasContent = document.querySelector('#detail-title, #detail-desc, [class*="noteContent"]') !== null;
            return hasAppPrompt && !hasContent;
        }
    """)
    if app_only:
        return f"这篇帖子仅限App查看，网页版被锁死了，换一个普通帖子试试。\n[debug] {state_status}"

    try:
        await page.wait_for_selector(
            '#detail-title, [class*="note-content"], [class*="noteContent"], [class*="detail-content"]',
            timeout=8000
        )
    except Exception:
        pass

    data = await page.evaluate("""() => {
        const title = document.querySelector('#detail-title')?.innerText?.trim()
            || document.querySelector('h1')?.innerText?.trim()
            || [...document.querySelectorAll('[class*="title"]')]
                .find(el => el.innerText?.trim() && el.tagName !== 'SCRIPT')?.innerText?.trim() || '';

        const desc = document.querySelector('#detail-desc .note-text')?.innerText?.trim()
            || document.querySelector('#detail-desc')?.innerText?.trim()
            || document.querySelector('[class*="noteContent"], [class*="note-content"]')?.innerText?.trim()
            || [...document.querySelectorAll('[class*="desc"], [class*="content"]')]
                .find(el => (el.innerText?.trim()?.length || 0) > 10 && el.tagName !== 'SCRIPT')
                ?.innerText?.trim() || '';

        const author = document.querySelector('.author-wrapper .username')?.innerText?.trim()
            || document.querySelector('.author-wrapper [class*="name"]')?.innerText?.trim()
            || document.querySelector('[class*="author"] [class*="name"]')?.innerText?.trim()
            || document.querySelector('[class*="username"]')?.innerText?.trim() || '';

        const likes = document.querySelector('.like-wrapper .count')?.innerText?.trim()
            || document.querySelector('[class*="like"] [class*="count"]')?.innerText?.trim() || '';

        const collects = document.querySelector('.collect-wrapper .count')?.innerText?.trim()
            || document.querySelector('[class*="collect"] [class*="count"]')?.innerText?.trim() || '';

        const comments = [...document.querySelectorAll('.comment-item, [class*="commentItem"], [class*="comment-item"]')]
            .slice(0, 5).map(c => ({
                user: c.querySelector('[class*="name"]')?.innerText?.trim() || '',
                text: c.querySelector('[class*="content"], [class*="text"]')?.innerText?.trim() || ''
            }));

        return { title, desc, author, likes, collects, comments };
    }""")

    if not data.get('title') and not data.get('desc'):
        page_text = await page.evaluate("() => document.body.innerText?.slice(0, 800) || ''")
        return f"无法解析帖子结构，页面原始内容（前800字）：\n{page_text}\n[debug] {state_status}"

    lines = [
        f"标题：{data['title'] or '(无标题)'}",
        f"作者：{data['author'] or '未知'}",
        f"正文：{data['desc'] or '(无内容)'}",
        f"点赞 {data['likes'] or 0}  |  收藏 {data['collects'] or 0}",
    ]
    if data.get("comments"):
        lines.append("\n评论：")
        for c in data["comments"]:
            if c.get("text"):
                lines.append(f"  {c['user']}：{c['text']}")
    return "\n".join(lines)


@mcp.tool()
async def xhs_get_feed() -> str:
    """获取小红书首页推荐的笔记列表。"""
    page = await get_page()
    await page.goto(f"{XHS_URL}/explore")
    await page.wait_for_load_state("networkidle", timeout=12000)
    await page.wait_for_timeout(1500)

    notes = await page.evaluate("""() => {
        const items = [...document.querySelectorAll('section.note-item')];
        return items.slice(0, 8).map(el => ({
            title: el.querySelector('.title span, [class*="title"]')?.innerText?.trim() || '',
            author: el.querySelector('.author .name, .name')?.innerText?.trim() || '',
            likes: el.querySelector('[class*="count"]')?.innerText?.trim() || '',
            url: el.querySelector('a')?.href || ''
        }));
    }""")

    if not notes:
        return "获取推荐内容失败，可能还没登录（先调用 xhs_login）。"

    lines = ["首页推荐：\n"]
    for i, n in enumerate(notes, 1):
        if n.get("title"):
            lines.append(f"{i}. {n['title']}")
            info = []
            if n.get("author"):
                info.append(n["author"])
            if n.get("likes"):
                info.append(f"{n['likes']}赞")
            if info:
                lines.append(f"   {'  ·  '.join(info)}")
            if n.get("url"):
                lines.append(f"   {n['url']}")
            lines.append("")
    return "\n".join(lines)


@mcp.tool()
async def xhs_like(url: str) -> str:
    """给一篇小红书笔记点赞。"""
    page = await get_page()
    await page.goto(url)
    await page.wait_for_load_state("networkidle", timeout=12000)
    await page.wait_for_timeout(1500)

    btn = await page.query_selector(".like-wrapper, [class*='like-wrapper']")
    if not btn:
        return "找不到点赞按钮，可能还没登录，或页面结构变了。"
    await btn.click()
    await page.wait_for_timeout(800)
    await save_cookies()
    return "点赞成功。"


@mcp.tool()
async def xhs_collect(url: str) -> str:
    """收藏一篇小红书笔记。"""
    page = await get_page()
    await page.goto(url)
    await page.wait_for_load_state("networkidle", timeout=12000)
    await page.wait_for_timeout(1500)

    btn = await page.query_selector(".collect-wrapper, [class*='collect-wrapper']")
    if not btn:
        return "找不到收藏按钮，可能还没登录，或页面结构变了。"
    await btn.click()
    await page.wait_for_timeout(800)
    await save_cookies()
    return "收藏成功。"


@mcp.tool()
async def xhs_comment(url: str, text: str) -> str:
    """在一篇小红书笔记下发评论。"""
    page = await get_page()
    await page.goto(url)
    await page.wait_for_load_state("networkidle", timeout=12000)
    await page.wait_for_timeout(1500)

    inp = await page.query_selector(".comment-input-inner, [class*='comment-input']")
    if not inp:
        return "找不到评论框，可能还没登录（先调用 xhs_login）。"

    await inp.click()
    await inp.type(text, delay=30)
    await page.wait_for_timeout(500)

    send = await page.query_selector("[class*='submit-btn'], button[class*='send']")
    if send:
        await send.click()
        await page.wait_for_timeout(800)
        await save_cookies()
        return f"评论已发送：{text}"
    return "内容填好了，但找不到发送按钮，请在浏览器里手动点发送。"


@mcp.tool()
async def xhs_post(title: str, content: str, style: str = "基础", tags: str = "") -> str:
    """在小红书发布图文笔记（文字转图片）。
    - title: 标题
    - content: 生成图片的文字内容
    - style: 卡片样式，可选：基础 / 插图 / 美漫 / 备忘 / 边框 / 清新（默认基础）
    - tags: 话题标签，逗号分隔，如 日常,分享,生活
    """
    page = await get_page()
    await page.goto("https://creator.xiaohongshu.com/publish/publish")
    await page.wait_for_load_state("networkidle", timeout=20000)
    await page.wait_for_timeout(2500)

    # 1. 先点"上传图文"tab
    await dom_click(page, "上传图文")
    await page.wait_for_timeout(1500)

    # 2. 点"文字配图"按钮
    clicked = await dom_click(page, "文字配图")
    if not clicked:
        return '找不到文字配图按钮，可能还没登录创作者平台（先调用 xhs_login_creator）。'
    await page.wait_for_timeout(1500)

    # 2. 填写文字内容
    content_area = await page.query_selector(
        "textarea, div[contenteditable='true'], [placeholder*='真诚'], [placeholder*='分享']"
    )
    if not content_area:
        return "找不到文字输入框。"
    await content_area.click()
    await page.keyboard.type(content, delay=20)
    await page.wait_for_timeout(500)

    # 3. 点"生成图片"
    gen_btn = page.get_by_text("生成图片", exact=True)
    if await gen_btn.count() == 0:
        return '找不到生成图片按钮。'
    await dom_click(page, "生成图片")
    await page.wait_for_timeout(5000)

    # 4. 选择卡片样式
    await dom_click(page, style)
    await page.wait_for_timeout(800)

    # 5. 点"下一步"
    clicked = await dom_click(page, "下一步")
    if not clicked:
        return '找不到下一步按钮，图片可能还没生成完，请在浏览器里手动操作。'
    await page.wait_for_timeout(2000)

    # 6. 填标题
    title_area = await page.query_selector("[placeholder*='标题']")
    if title_area:
        await title_area.click()
        await page.keyboard.type(title, delay=20)
        await page.wait_for_timeout(500)

    # 7. 添加话题标签
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        for tag in tag_list:
            topic_btn = page.get_by_text("话题", exact=True)
            if await topic_btn.count() > 0:
                await topic_btn.first.click()
                await page.wait_for_timeout(800)
                tag_input = await page.query_selector("[placeholder*='搜索'], [placeholder*='话题']")
                if tag_input:
                    await tag_input.type(tag, delay=30)
                    await page.wait_for_timeout(1000)
                    first_result = await page.query_selector("[class*='topic-item'], [class*='result'] li")
                    if first_result:
                        await first_result.click()
                        await page.wait_for_timeout(500)

    # 8. 点"发布"
    if await dom_click(page, "发布"):
        await page.wait_for_timeout(2000)
        await save_cookies()
        return f"发布成功！标题：{title}，样式：{style}" + (f"，标签：{tags}" if tags else "")

    await save_cookies()
    return "内容和图片都填好了，但找不到发布按钮，请在浏览器里手动点发布。"


if __name__ == "__main__":
    mcp.run(transport="stdio")
