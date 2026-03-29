# gemini-exporter

Download Gemini shared chat conversations to Markdown or JSON.

## Requirements

```bash
pip install playwright
python -m playwright install chromium
```

## Usage

```bash
# Save as Markdown (default, auto-named from conversation title)
python download.py https://gemini.google.com/share/XXXXXXXXXX

# Specify output file
python download.py https://gemini.google.com/share/XXXXXXXXXX output.md

# Save as JSON
python download.py https://gemini.google.com/share/XXXXXXXXXX output.json
```

## Output example (Markdown)

```markdown
# Conversation Title

**Share URL:** https://gemini.google.com/share/XXXXXXXXXX
**Messages:** 42

---

**user:**

your question here

**Gemini:**

Gemini's response here

---
```

## How it works

Playwright loads the share page and intercepts the internal `batchexecute` API call that delivers the full conversation data. The nested JSON is parsed to extract all user and model turns.
