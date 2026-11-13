# {{TITLE}}

Rules workspace created from the Fred Lobster blank template.

- Rule content lives in `docs/`.
- The site configuration and version stamp live in `mkdocs.yml`.
- Publish through the race rules manager (`fred publish` or the Admin GUI) rather
  than editing the built `site/` output.

## Local preview

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdocs serve
```
