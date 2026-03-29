# gemini-exporter

Download Gemini shared chat conversations to Markdown or JSON, with attachments.

## Requirements

```bash
pip install playwright httpx
python -m playwright install chromium
```

## Usage

```bash
# Save as Markdown with attachments (default)
python download.py https://gemini.google.com/share/XXXXXXXXXX

# Specify output file
python download.py https://gemini.google.com/share/XXXXXXXXXX output.md

# Save as JSON
python download.py https://gemini.google.com/share/XXXXXXXXXX output.json

# Skip attachment download
python download.py --no-dl https://gemini.google.com/share/XXXXXXXXXX
```

## Output structure

```
output.md
output/
  attachments/
    turn003_0.png
    turn005_0.png
    turn005_1.pdf
    ...
```

## Output example (Markdown)

```markdown
**user:**

file:turn003_0.png
これでDBどれぐらい使えるん？

![turn003_0.png](output/attachments/turn003_0.png)

**Gemini:**

Gemini's response here
```

Attachments are referenced as relative paths in the Markdown.
When `--no-dl` is used, original URLs are embedded instead.

## How it works

Playwright loads the share page and intercepts the internal `batchexecute` API call that delivers the full conversation data. The nested JSON is parsed to extract all user/model turns and file attachments (images, PDFs, etc.).
