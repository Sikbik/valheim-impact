# Valheim Impact tracker

The public [project tracker](https://sikbik.github.io/valheim-impact/) follows the
original [Valheim Impact project](https://github.com/Sikbik/valheim-impact).
This React/Vite static page combines a Nordic fantasy design with exact asset inventories, biome
checkpoints, project milestones and scoped validation evidence.

## Develop

Use Node 24.20.0 and the pinned npm lockfile. From the repository root:

```sh
npm ci --prefix status-site
python tools/refresh_tracker.py
npm run dev --prefix status-site -- --host 127.0.0.1
```

Open the local address reported by the dev server. To verify the public build:

```sh
python tools/refresh_tracker.py --check
npm test --prefix status-site
GITHUB_PAGES=true npm run build --prefix status-site
```

GitHub Actions publishes `status-site/dist/client` after the source verification
workflow passes on `main`. The static export uses `/valheim-impact` as its base
path. All data and artwork are served from the same Pages site.

The metadata catalog and evidence manifest drive checkmarks. A pull request is
not a completed asset. The overall progress formula excludes discovery, and
biome approval has separate review gates. See
[status tracking](../docs/STATUS_TRACKING.md) and
[contribution instructions](../CONTRIBUTING.md).

Original website artwork has per-file hashes in `public/art/provenance.json`.
Code is MIT licensed; artwork is CC BY 4.0 with
[project attribution](../assets/ATTRIBUTION.md). No original game pixels or
geometry are hosted by this page.
