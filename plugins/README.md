# Tungsten plugins

Official plugins for Tungsten. Each folder is its own pip package with its own version.

| Folder | Package | What it adds |
| --- | --- | --- |
| [leads](leads) | `tungsten-leads` | Leads list, stages, timeline and your own lead form fields |
| [meta-leads](meta-leads) | `tungsten-meta-leads` | Facebook and Instagram lead form leads, with one-click setup (needs `tungsten-leads`) |
| [whatsapp](whatsapp) | `tungsten-whatsapp` | WhatsApp for leads: click-to-chat, Cloud API or WhatsApp Web (needs `tungsten-leads`) |
| [mcp](mcp) | `tungsten-mcp` | An MCP server, so AI assistants like Claude can read and change your panel's data |
| [security-audit](security-audit) | `tungsten-security-audit` | A security audit with a score and fix tips, plus a login log with lockout |

## Working on a plugin

```bash
pip install -e ".[dev]" -e plugins/leads -e plugins/meta-leads -e plugins/whatsapp -e plugins/mcp -e plugins/security-audit
for p in leads meta-leads whatsapp mcp security-audit; do pytest plugins/$p/tests || break; done
```

## Releasing a plugin

```bash
cd plugins/leads
python -m build
twine upload dist/*
```
