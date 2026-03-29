#!/usr/bin/env python3
"""
Gemini Share Chat Downloader
Usage: python download.py [--no-images] <gemini_share_url> [output_file]
Example: python download.py https://gemini.google.com/share/49fb916f92a0
"""

import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from playwright.async_api import async_playwright

MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _extract_attachments(user_msg_parts: list) -> list[dict]:
    """Extract attachment info from user message parts.

    Attachments live at user_msg_parts[4] as a list of groups,
    each group having a file list at index [3].
    """
    attachments = []
    if len(user_msg_parts) <= 4 or not user_msg_parts[4]:
        return attachments

    for group in user_msg_parts[4]:
        if not group or len(group) <= 3 or not group[3]:
            continue
        for file_entry in group[3]:
            try:
                url = file_entry[3] if len(file_entry) > 3 else None
                mime = file_entry[11] if len(file_entry) > 11 else None
                filename = file_entry[2] if len(file_entry) > 2 else None
                if url and isinstance(url, str) and url.startswith("http"):
                    attachments.append({
                        "url": url,
                        "mime": mime,
                        "original_name": filename,
                    })
            except (IndexError, TypeError):
                continue

    return attachments


def parse_conversation(raw_body: str) -> dict:
    """Parse the batchexecute response body into a structured conversation."""
    lines = raw_body.split("\n")

    json_line = None
    for line in lines:
        if line.startswith("[["):
            json_line = line
            break

    if not json_line:
        raise ValueError("Could not find JSON data in response")

    outer = json.loads(json_line)
    try:
        inner_str = outer[0][2]
    except (IndexError, TypeError):
        raise ValueError("Unexpected API response structure")
    if not inner_str:
        raise ValueError("No conversation data in response (inner_str is empty)")

    inner = json.loads(inner_str)

    if not inner or not isinstance(inner[0], list):
        raise ValueError("Unexpected conversation structure")

    conv_data = inner[0]
    if len(conv_data) < 2:
        raise ValueError("Unexpected conversation structure (missing turns)")

    turns_raw = conv_data[1]

    meta = conv_data[2] if len(conv_data) > 2 and conv_data[2] else None
    title = meta[1] if meta and len(meta) > 1 and isinstance(meta[1], str) else "Untitled"
    share_id = conv_data[3] if len(conv_data) > 3 else "unknown"

    if not turns_raw:
        raise ValueError("No turns found in conversation data")

    messages = []
    for i, turn in enumerate(turns_raw):
        try:
            user_parts = turn[2][0] if turn[2] and turn[2][0] else []
            user_text = user_parts[0] if user_parts else ""
            if not isinstance(user_text, str):
                user_text = str(user_text)

            attachments = _extract_attachments(user_parts)

            model_text = ""
            if turn[3] and turn[3][0] and turn[3][0][0]:
                candidate = turn[3][0][0]
                if len(candidate) > 1 and candidate[1]:
                    chunks = candidate[1]
                    if isinstance(chunks, list):
                        model_text = "".join(
                            c for c in chunks if isinstance(c, str)
                        )
                    elif isinstance(chunks, str):
                        model_text = chunks

            if user_text or model_text:
                messages.append({
                    "index": i,
                    "user": user_text,
                    "model": model_text,
                    "attachments": attachments,
                })
        except Exception as e:
            print(f"[!] Skipping malformed turn {i}: {e}", file=sys.stderr)

    return {
        "title": title,
        "share_id": share_id,
        "messages": messages,
    }


async def download_images(messages: list, image_dir: Path) -> None:
    """Download all attachments to image_dir, updating each attachment dict
    with a 'local_path' key pointing to the saved file."""
    to_download = []
    for msg in messages:
        for j, att in enumerate(msg.get("attachments", [])):
            ext = MIME_TO_EXT.get(att.get("mime"), ".png")
            filename = f"turn{msg['index']:03d}_{j}{ext}"
            dest = image_dir / filename
            att["local_path"] = str(dest)
            att["filename"] = filename
            to_download.append((att["url"], dest))

    if not to_download:
        return

    image_dir.mkdir(parents=True, exist_ok=True)
    print(f"[+] Downloading {len(to_download)} images...", file=sys.stderr)

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for i, (url, dest) in enumerate(to_download):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            except Exception as e:
                print(f"[!] Failed to download {dest.name}: {e}", file=sys.stderr)

    downloaded = sum(1 for _, d in to_download if d.exists())
    print(f"[+] Downloaded {downloaded}/{len(to_download)} images", file=sys.stderr)


def conversation_to_markdown(conv: dict, image_dir_name: str = None) -> str:
    """Convert parsed conversation to Markdown format."""
    lines = []
    lines.append(f"# {conv['title']}")
    lines.append(f"\n**Share URL:** https://gemini.google.com/share/{conv['share_id']}")
    lines.append(f"**Messages:** {len(conv['messages'])}\n")
    lines.append("---\n")

    for msg in conv["messages"]:
        if msg["user"]:
            lines.append(f"**user:**\n\n{msg['user']}\n")
        for att in msg.get("attachments", []):
            if image_dir_name and att.get("filename"):
                lines.append(f"![{att['filename']}]({image_dir_name}/{att['filename']})\n")
            else:
                lines.append(f"![image]({att['url']})\n")
        if msg["model"]:
            lines.append(f"**Gemini:**\n\n{msg['model']}\n")
        lines.append("---\n")

    return "\n".join(lines)


def conversation_to_json(conv: dict) -> str:
    """Convert parsed conversation to JSON format."""
    return json.dumps(conv, ensure_ascii=False, indent=2)


async def download_chat(
    url: str,
    output_path: str = None,
    fmt: str = "md",
    save_images: bool = True,
) -> dict:
    """Download a Gemini shared chat conversation."""

    if not re.fullmatch(r"https://gemini\.google\.com/share/[a-zA-Z0-9]+", url):
        raise ValueError(f"Invalid Gemini share URL: {url}")

    print(f"[+] Loading: {url}", file=sys.stderr)

    conversation_body = None
    api_received = asyncio.Event()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()

            async def on_response(response):
                nonlocal conversation_body
                if "batchexecute" in response.url and "ujx1Bf" in response.url:
                    try:
                        body = await response.text()
                        if conversation_body is None or len(body) > len(conversation_body):
                            conversation_body = body
                            api_received.set()
                    except Exception as e:
                        print(f"[!] Failed to read API response: {e}", file=sys.stderr)

            page.on("response", on_response)

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await asyncio.wait_for(api_received.wait(), timeout=15)
            except asyncio.TimeoutError:
                pass
        finally:
            await browser.close()

    if not conversation_body:
        raise RuntimeError("No conversation data captured. The URL may be invalid or expired.")

    print("[+] Parsing conversation...", file=sys.stderr)
    conv = parse_conversation(conversation_body)

    image_count = sum(len(m.get("attachments", [])) for m in conv["messages"])
    print(
        f"[+] Found {len(conv['messages'])} messages, "
        f"{image_count} images: \"{conv['title']}\"",
        file=sys.stderr,
    )

    # Determine output path
    if not output_path:
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", conv["title"])[:60].strip()
        if not safe_title:
            safe_title = conv["share_id"]
        ext = fmt if fmt in ("md", "json") else "md"
        output_path = f"{safe_title}.{ext}"

    output_p = Path(output_path)

    # Download images
    image_dir_name = None
    if save_images and image_count > 0:
        image_dir = output_p.with_suffix("") / "images"
        image_dir_name = f"{output_p.stem}/images"
        await download_images(conv["messages"], image_dir)

    # Write output
    if output_path.endswith(".json") or fmt == "json":
        content = conversation_to_json(conv)
    else:
        content = conversation_to_markdown(conv, image_dir_name)

    output_p.write_text(content, encoding="utf-8")
    print(f"[+] Saved to: {output_path}", file=sys.stderr)

    return conv


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    args = sys.argv[1:]
    save_images = True
    if "--no-images" in args:
        save_images = False
        args.remove("--no-images")

    url = args[0]
    output = args[1] if len(args) > 1 else None

    fmt = "md"
    if output and output.endswith(".json"):
        fmt = "json"

    try:
        asyncio.run(download_chat(url, output, fmt, save_images))
    except (ValueError, RuntimeError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[!] Cancelled", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
