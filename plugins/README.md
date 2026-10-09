# Tungsten plugins

Official plugins for Tungsten. Each folder is its own pip package with its own version.

| Folder | Package | What it adds |
| --- | --- | --- |
| [leads](leads) | `tungsten-leads` | Leads list, stages, timeline and your own lead form fields |
| [meta-leads](meta-leads) | `tungsten-meta-leads` | Facebook and Instagram lead form leads, with one-click setup (needs `tungsten-leads`) |
| [whatsapp](whatsapp) | `tungsten-whatsapp` | WhatsApp for leads: click-to-chat, Cloud API or WhatsApp Web (needs `tungsten-leads`) |
| [mcp](mcp) | `tungsten-mcp` | An MCP server, so AI assistants like Claude can read and change your panel's data |
| [blog](blog) | `tungsten-blog` | A blog built for SEO, GEO and AEO, with a live score in the editor, schema.org data, sitemap and llms.txt |

## Working on a plugin

```bash
pip install -e ".[dev]" -e plugins/leads -e plugins/meta-leads -e plugins/whatsapp -e plugins/mcp -e plugins/blog
pytest plugins/leads/tests plugins/meta-leads/tests plugins/whatsapp/tests plugins/mcp/tests plugins/blog/tests
```

## Releasing a plugin

```bash
cd plugins/leads
python -m build
twine upload dist/*
```
