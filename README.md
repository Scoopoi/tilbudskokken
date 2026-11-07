# Tilbudskøkkenet

App der kombinerer ugens tilbud fra eTilbudsavis med opskrifter og kalorier til Lifesum.

- `index.html` – selve appen
- `hent_tilbud.py` – henter tilbud til `offers.json` (bruges hvis appen ikke kan hente live)
- `build_app.py` – bygger den installerbare app i `docs/` (det GitHub Pages viser)

Opdatér appen: `python build_app.py`, derefter `git add -A`, `git commit -m "..."` og `git push`.
