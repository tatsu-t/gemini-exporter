# gemini-exporter

Download Gemini shared chat conversations to Markdown or JSON, with image attachments.

## Requirements

```bash
pip install playwright httpx
python -m playwright install chromium
```

## Usage

```bash
# Save as Markdown with images (default)
python download.py https://gemini.google.com/share/XXXXXXXXXX

# Specify output file
python download.py https://gemini.google.com/share/XXXXXXXXXX output.md

# Save as JSON
python download.py https://gemini.google.com/share/XXXXXXXXXX output.json

# Skip image download
python download.py --no-images https://gemini.google.com/share/XXXXXXXXXX
```

## Output structure

```
output.md
output/
  images/
    turn003_0.png
    turn005_0.png
    turn005_1.png
    ...
```

Images are referenced as relative paths in the Markdown file.
When `--no-images` is used, images are linked by their original URLs instead.

## How it works

Playwright loads the share page and intercepts the internal `batchexecute` API call that delivers the full conversation data. The nested JSON is parsed to extract all user/model turns and image attachments.
