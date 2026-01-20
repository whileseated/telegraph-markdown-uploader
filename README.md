# Telegraph Markdown Uploader

Upload Markdown files to Telegraph.

## Installation

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Upload a markdown file
python telegraph_upload.py article.md

# With custom title and author
python telegraph_upload.py article.md --title "Custom Title" --author "Author Name"

# Blank out a published page
python telegraph_upload.py --blank "https://telegra.ph/Your-Page-01-20"
```

## Front-matter

The script recognizes this optional front-matter format:

```markdown
# Title

By Author Name

Published: 2026-01-20 on [newyorker.com](https://www.newyorker.com/example)

Word count: 1,500

---
Article body starts here...
```

When front-matter is present, the title and author are extracted automatically, and a "via [source](url)" link is added to the top of the Telegraph page.

## Files

- `.telegraph_token` - Auto-generated API token (keep private)
- `log.txt` - Record of published URLs
