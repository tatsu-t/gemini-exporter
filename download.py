#!/usr/bin/env python3
"""
Gemini Share Chat Downloader
Usage: python download.py <gemini_share_url> [output_file]
Example: python download.py https://gemini.google.com/share/49fb916f92a0
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright


def parse_conversation(raw_body: str) -> dict:
    """Parse the batchexecute response body into a structured conversation."""
    lines = raw_body.split("\n")

    # Format: )]}'\n\n<length>\n<json>\n...
    json_line = None
    for line in lines:
        if line.startswith("[["):
            json_line = line
            break

    if not json_line:
        raise ValueError("Could not find JSON data in response")

    outer = json.loads(json_line)
    inner_str = outer[0][2]
    if not inner_str:
        raise ValueError("No conversation data in response (inner_str is empty)")

    inner = json.loads(inner_str)

    if not inner or not isinstance(inner[0], list):
        raise ValueError("Unexpected conversation structure")

    conv_data = inner[0]
    if len(conv_data) < 2:
        raise ValueError("Unexpected conversation structure (missing turns)")

    turns_raw = conv_data[1]  # list of all turns

    # Extract title and share_id
    meta = conv_data[2] if len(conv_data) > 2 and conv_data[2] else None
    title = meta[1] if meta and len(meta) > 1 and isinstance(meta[1], str) else "Untitled"
    share_id = conv_data[3] if len(conv_data) > 3 else "unknown"

    if not turns_raw:
        raise ValueError("No turns found in conversation data")

    messages = []
    for i, turn in enumerate(turns_raw):
        try:
            # User message: turn[2][0][0] is the text
            user_parts = turn[2][0] if turn[2] and turn[2][0] else []
            user_text = user_parts[0] if user_parts else ""
            if not isinstance(user_text, str):
                user_text = str(user_text)

            # Model response: turn[3][0][0][1] is list of text chunks
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
                })
        except Exception as e:
            print(f"[!] Skipping malformed turn {i}: {e}", file=sys.stderr)

    return {
        "title": title,
        "share_id": share_id,
        "messages": messages,
    }


def conversation_to_markdown(conv: dict) -> str:
    """Convert parsed conversation to Markdown format."""
    lines = []
    lines.append(f"# {conv['title']}")
    lines.append(f"\n**Share URL:** https://gemini.google.com/share/{conv['share_id']}")
    lines.append(f"**Messages:** {len(conv['messages'])}\n")
    lines.append("---\n")

    for msg in conv["messages"]:
        if msg["user"]:
            lines.append(f"**user:**\n\n{msg['user']}\n")
        if msg["model"]:
            lines.append(f"**Gemini:**\n\n{msg['model']}\n")
        lines.append("---\n")

    return "\n".join(lines)


def conversation_to_json(conv: dict) -> str:
    """Convert parsed conversation to JSON format."""
    return json.dumps(conv, ensure_ascii=False, indent=2)


async def download_chat(url: str, output_path: str = None, fmt: str = "md") -> dict:
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
                        # Keep the largest response (the full conversation)
                        if conversation_body is None or len(body) > len(conversation_body):
                            conversation_body = body
                            api_received.set()
                    except Exception as e:
                        print(f"[!] Failed to read API response: {e}", file=sys.stderr)

            page.on("response", on_response)

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait for the conversation API call, with a 15s timeout fallback
            try:
                await asyncio.wait_for(api_received.wait(), timeout=15)
            except asyncio.TimeoutError:
                pass  # proceed and let the None check below raise a clear error
        finally:
            await browser.close()

    if not conversation_body:
        raise RuntimeError("No conversation data captured. The URL may be invalid or expired.")

    print("[+] Parsing conversation...", file=sys.stderr)
    conv = parse_conversation(conversation_body)
    print(f"[+] Found {len(conv['messages'])} messages: \"{conv['title']}\"", file=sys.stderr)

    # Determine output path
    if not output_path:
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", conv["title"])[:60].strip()
        if not safe_title:
            safe_title = conv["share_id"]
        ext = fmt if fmt in ("md", "json") else "md"
        output_path = f"{safe_title}.{ext}"

    # Write output
    if output_path.endswith(".json") or fmt == "json":
        content = conversation_to_json(conv)
    else:
        content = conversation_to_markdown(conv)

    Path(output_path).write_text(content, encoding="utf-8")
    print(f"[+] Saved to: {output_path}", file=sys.stderr)

    return conv


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    url = sys.argv[1]
    output = sys.argv[2] if len(sys.argv) > 2 else None

    # Detect format from output filename
    fmt = "md"
    if output and output.endswith(".json"):
        fmt = "json"

    asyncio.run(download_chat(url, output, fmt))


if __name__ == "__main__":
    main()
