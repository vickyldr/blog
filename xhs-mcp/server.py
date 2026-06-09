#!/usr/bin/env python3
"""
小红书 MCP Server
用 Playwright 控制浏览器，支持：搜索 / 看帖 / 点赞 / 收藏 / 评论 / 发帖
"""

import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright

COOKIES_FILE = Path.home() / ".xhs_cookies.json"
XHS_URL = "https://www.xiaohongshu.com"

mcp = FastMCP("小红书")

_pw = None
_browser = None
_ctx = None
_page = None


async def get_page():
    global _pw, _browser, _ctx, _page
    if _page and not _page.is_closed():
        return _page

    _pw = await async_playwright().start()
    _browser = await _pw.chromium.launch(headless=False, slow_mo=50)
    _ctx = await _browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    if COOKIES_FILE.exists():
        cookies = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
        await _ctx.add_cookies(cookies)

    _page = await _ctx.new_page()
    return _page


async def save_cookies():
    if _ctx:
        cookies = await _ctx.cookies()
        COOKIES_FILE.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")


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
    return "登录状态已保存。"


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
    await page.goto(url)
    await page.wait_for_load_state("networkidle", timeout=12000)
    await page.wait_for_timeout(1500)

    data = await page.evaluate("""() => {
        const title = document.querySelector('#detail-title')?.innerText?.trim()
            || document.querySelector('[class*="title"]')?.innerText?.trim() || '';
        const desc = document.querySelector('#detail-desc')?.innerText?.trim()
            || document.querySelector('[class*="desc"]')?.innerText?.trim() || '';
        const author = document.querySelector('.author-wrapper .username, [class*="username"]')?.innerText?.trim() || '';
        const likes = document.querySelector('.like-wrapper .count, [class*="like-count"]')?.innerText?.trim() || '';
        const collects = document.querySelector('.collect-wrapper .count, [class*="collect-count"]')?.innerText?.trim() || '';
        const comments = [...document.querySelectorAll('.comment-item')].slice(0, 5).map(c => ({
            user: c.querySelector('[class*="name"]')?.innerText?.trim() || '',
            text: c.querySelector('[class*="content"]')?.innerText?.trim() || ''
        }));
        return { title, desc, author, likes, collects, comments };
    }""")

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
async def xhs_post(title: str, content: str) -> str:
    """在小红书发布一篇文字笔记。会打开创作者后台，填好内容后需要你在浏览器里手动点发布。"""
    page = await get_page()
    await page.goto("https://creator.xiaohongshu.com/publish/publish")
    await page.wait_for_load_state("networkidle", timeout=15000)
    await page.wait_for_timeout(2000)

    text_tab = await page.query_selector("[class*='text-tab'], [data-type='text']")
    if text_tab:
        await text_tab.click()
        await page.wait_for_timeout(800)

    title_inp = await page.query_selector("input[placeholder*='标题'], input[placeholder*='title']")
    if title_inp:
        await title_inp.fill(title)

    content_inp = await page.query_selector("[placeholder*='正文'], [contenteditable='true']")
    if content_inp:
        await content_inp.click()
        await content_inp.type(content, delay=20)

    await save_cookies()
    return f"标题和正文已填好（标题：{title}），请在浏览器里确认内容后手动点发布按钮。"


if __name__ == "__main__":
    mcp.run(transport="stdio")
