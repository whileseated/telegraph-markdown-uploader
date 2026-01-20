#!/usr/bin/env python3
"""
Upload Markdown files to Telegraph.

Usage:
    python telegraph_upload.py <markdown_file> [--title "Custom Title"] [--author "Author Name"]
    python telegraph_upload.py --blank "Your-Page-Title-01-20"
    python telegraph_upload.py --blank "https://telegra.ph/Your-Page-Title-01-20"

First run will create a Telegraph account and save the token locally.
"""

import argparse
from datetime import datetime
import json
import os
import re
import sys
from pathlib import Path

import requests
import markdown
from bs4 import BeautifulSoup

# Telegraph API base URL
API_BASE = "https://api.telegra.ph"

# Token file location (same directory as script)
TOKEN_FILE = Path(__file__).parent / ".telegraph_token"

# Log file for published URLs
LOG_FILE = Path(__file__).parent / "log.txt"

# Content size limit (~64KB)
MAX_CONTENT_SIZE = 64000


def get_or_create_token(short_name: str = "anon") -> str:
    """Get existing token or create a new Telegraph account."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()

    response = requests.get(f"{API_BASE}/createAccount", params={
        "short_name": short_name
    })
    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise Exception(f"Failed to create account: {result}")

    token = result["result"]["access_token"]
    TOKEN_FILE.write_text(token)
    print(f"Created new Telegraph account. Token saved to {TOKEN_FILE}")
    return token


def html_to_telegraph_nodes(html: str) -> list:
    """Convert HTML to Telegraph's node format."""
    soup = BeautifulSoup(html, "html.parser")

    def process_element(element):
        """Recursively process an HTML element into Telegraph nodes."""
        if isinstance(element, str):
            text = element
            if text.strip():
                return text
            return None

        tag_name = element.name

        # Map HTML tags to Telegraph-supported tags
        tag_map = {
            "h1": "h3",
            "h2": "h3",
            "h3": "h4",
            "h4": "h4",
            "h5": "h4",
            "h6": "h4",
            "p": "p",
            "a": "a",
            "strong": "strong",
            "b": "strong",
            "em": "em",
            "i": "em",
            "u": "u",
            "s": "s",
            "strike": "s",
            "del": "s",
            "code": "code",
            "pre": "pre",
            "blockquote": "blockquote",
            "ul": "ul",
            "ol": "ol",
            "li": "li",
            "br": "br",
            "hr": "hr",
            "img": "img",
            "figure": "figure",
            "figcaption": "figcaption",
            "aside": "aside",
        }

        telegraph_tag = tag_map.get(tag_name)

        # Skip unsupported tags but process their children
        if telegraph_tag is None:
            children = []
            for child in element.children:
                processed = process_element(child)
                if processed:
                    if isinstance(processed, list):
                        children.extend(processed)
                    else:
                        children.append(processed)
            return children if children else None

        # Build the node
        node = {"tag": telegraph_tag}

        # Handle attributes
        attrs = {}
        if tag_name == "a" and element.get("href"):
            attrs["href"] = element["href"]
        if tag_name == "img" and element.get("src"):
            attrs["src"] = element["src"]

        if attrs:
            node["attrs"] = attrs

        # Handle self-closing tags
        if telegraph_tag in ("br", "hr"):
            return node

        # Process children
        children = []
        for child in element.children:
            processed = process_element(child)
            if processed:
                if isinstance(processed, list):
                    children.extend(processed)
                else:
                    children.append(processed)

        if children:
            node["children"] = children

        return node

    nodes = []
    for element in soup.children:
        processed = process_element(element)
        if processed:
            if isinstance(processed, list):
                nodes.extend(processed)
            else:
                nodes.append(processed)

    # Wrap plain text in paragraphs
    final_nodes = []
    for node in nodes:
        if isinstance(node, str):
            final_nodes.append({"tag": "p", "children": [node]})
        else:
            final_nodes.append(node)

    return final_nodes


def markdown_to_telegraph_nodes(md_content: str) -> list:
    """Convert Markdown to Telegraph nodes."""
    # Convert markdown to HTML
    html = markdown.markdown(
        md_content,
        extensions=["extra", "codehilite", "nl2br"]
    )

    # Convert HTML to Telegraph nodes
    return html_to_telegraph_nodes(html)


def extract_title_from_markdown(md_content: str) -> str | None:
    """Try to extract a title from the markdown (first h1)."""
    match = re.match(r"^#\s+(.+)$", md_content.strip(), re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


def parse_front_matter(md_content: str) -> tuple[dict, str]:
    """
    Parse front-matter from markdown content.

    Expected format:
        # Title
        By Author Name
        Published: YYYY-MM-DD on [source](url)
        Word count: N
        ---
        Body content...

    Returns:
        (metadata dict, body content without front-matter)
    """
    metadata = {}
    lines = md_content.split('\n')
    body_start = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Title line
        if stripped.startswith('# '):
            metadata['title'] = stripped[2:].strip()
            continue

        # Author line
        if stripped.startswith('By '):
            metadata['author'] = stripped[3:].strip()
            continue

        # Published line - extract source link if present
        if stripped.startswith('Published:'):
            metadata['published'] = stripped
            # Extract the source link: "on [source](url)"
            source_match = re.search(r'on \[([^\]]+)\]\(([^)]+)\)', stripped)
            if source_match:
                metadata['source_name'] = source_match.group(1)
                metadata['source_url'] = source_match.group(2)
            continue

        # Word count line
        if stripped.startswith('Word count:'):
            metadata['word_count'] = stripped
            continue

        # Horizontal rule marks end of front-matter
        if stripped == '---':
            body_start = i + 1
            break

        # Empty lines in front-matter are ok
        if stripped == '':
            continue

        # If we hit non-front-matter content, stop
        break

    # If we found front-matter, return body without it
    if metadata and body_start > 0:
        body = '\n'.join(lines[body_start:]).strip()
        return metadata, body

    # No front-matter found, return original content
    return {}, md_content


def create_page(token: str, title: str, content: list, author_name: str = None) -> dict:
    """Create a Telegraph page."""
    content_json = json.dumps(content)

    # Check size limit
    if len(content_json) > MAX_CONTENT_SIZE:
        raise Exception(
            f"Content too large: {len(content_json)} bytes "
            f"(max {MAX_CONTENT_SIZE} bytes, ~{MAX_CONTENT_SIZE // 1000}KB)"
        )

    data = {
        "access_token": token,
        "title": title[:256],  # Telegraph title limit
        "content": content_json,
        "return_content": "false"
    }

    if author_name:
        data["author_name"] = author_name[:128]  # Telegraph author limit

    response = requests.post(f"{API_BASE}/createPage", data=data)
    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise Exception(f"Failed to create page: {result}")

    return result["result"]


def blank_page(token: str, path: str) -> dict:
    """Blank out an existing Telegraph page."""
    # Extract just the path if a full URL was provided
    if path.startswith("http"):
        path = path.split("/")[-1]

    data = {
        "access_token": token,
        "path": path,
        "title": "[Removed]",
        "content": json.dumps([{"tag": "p", "children": ["[This page has been removed]"]}])
    }

    response = requests.post(f"{API_BASE}/editPage", data=data)
    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise Exception(f"Failed to blank page: {result}")

    return result["result"]


def main():
    parser = argparse.ArgumentParser(
        description="Upload a Markdown file to Telegraph"
    )
    parser.add_argument("file", nargs="?", help="Path to the Markdown file")
    parser.add_argument("--title", "-t", help="Page title (default: extracted from markdown or filename)")
    parser.add_argument("--author", "-a", help="Author name (optional)")
    parser.add_argument("--account-name", default="anon", help="Short name for new Telegraph account")
    parser.add_argument("--blank", "-b", metavar="PATH", help="Blank out a page (provide path or full URL)")

    args = parser.parse_args()

    # Get or create token
    token = get_or_create_token(args.account_name)

    # Handle --blank mode
    if args.blank:
        print(f"Blanking page: {args.blank}")
        result = blank_page(token, args.blank)
        print(f"Page blanked: {result['url']}")
        return result["url"]

    # Normal upload mode requires a file
    if not args.file:
        parser.error("A markdown file is required (or use --blank to blank a page)")

    # Read the markdown file
    md_path = Path(args.file)
    if not md_path.exists():
        print(f"Error: File not found: {md_path}", file=sys.stderr)
        sys.exit(1)

    md_content = md_path.read_text(encoding="utf-8")

    # Parse front-matter if present
    metadata, body_content = parse_front_matter(md_content)

    # Determine title (priority: CLI arg > front-matter > first h1 > filename)
    title = args.title or metadata.get('title') or extract_title_from_markdown(md_content) or md_path.stem

    # Determine author (priority: CLI arg > front-matter)
    author = args.author or metadata.get('author')

    # Prepend "via [source](url)" if source link was in front-matter
    if metadata.get('source_url'):
        source_line = f"via [{metadata['source_name']}]({metadata['source_url']})\n\n"
        body_content = source_line + body_content

    # Use body content (without front-matter) if front-matter was found
    content_to_convert = body_content if metadata else md_content

    # Convert markdown to Telegraph nodes
    print(f"Converting: {md_path.name}")
    nodes = markdown_to_telegraph_nodes(content_to_convert)

    content_size = len(json.dumps(nodes))
    print(f"Content size: {content_size:,} bytes ({content_size * 100 // MAX_CONTENT_SIZE}% of limit)")

    # Create the page
    print(f"Uploading: \"{title}\"")
    result = create_page(token, title, nodes, author)

    print(f"\nPublished: {result['url']}")
    print(f"Path: {result['path']}")

    # Log the published URL
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp}\t{result['url']}\t{title}\n")

    return result["url"]


if __name__ == "__main__":
    main()
