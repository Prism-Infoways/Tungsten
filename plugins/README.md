# Tungsten plugins

Official plugins for Tungsten. Each folder is its own pip package with its own version.

| Folder | Package | What it adds |
| --- | --- | --- |
| [leads](leads) | `tungsten-leads` | Leads list, stages, timeline and your own lead form fields |

## Working on a plugin

```bash
pip install -e ".[dev]" -e plugins/leads
pytest plugins/leads/tests
```

## Releasing a plugin

```bash
cd plugins/leads
python -m build
twine upload dist/*
```
