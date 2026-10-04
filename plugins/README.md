# Tungsten plugins

Official plugins for Tungsten. Each folder is its own pip package with its own version.

| Folder | Package | What it adds |
| --- | --- | --- |
| [leads](leads) | `tungsten-leads` | Leads list, stages, timeline and your own lead form fields |
| [meta-leads](meta-leads) | `tungsten-meta-leads` | Facebook and Instagram lead form leads, with one-click setup (needs `tungsten-leads`) |

## Working on a plugin

```bash
pip install -e ".[dev]" -e plugins/leads -e plugins/meta-leads
pytest plugins/leads/tests plugins/meta-leads/tests
```

## Releasing a plugin

```bash
cd plugins/leads
python -m build
twine upload dist/*
```
