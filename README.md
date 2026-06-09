# Statistical Principles and Orthogonality — Online Edition

An online, searchable edition of the master's thesis **"Statistical Principles and
Orthogonality To the Flight of the Constellation"** by **Angelo Perillo**
(advisor: Richard Fowles).

The site reflows the thesis prose into responsive, accessible, fully searchable
HTML, while every equation, figure and table is embedded as a high-resolution image
cropped straight from the PDF — so the mathematics stays pixel-exact. The original
PDF is always one click away.

## How it works

The PDF is the single source of truth. A Python pipeline extracts the content and an
Astro site renders it:

```
Angelo_Final_Project.pdf          ← source thesis (the only hand-maintained input)
pipeline/
  extract.py                      ← PDF → structured JSON + cropped images
  requirements.txt
site/                             ← Astro static site
  src/
    data/thesis.json              ← generated content model (git-ignored)
    lib/content.js                ← groups sections into reader chapters
    components/  layouts/  pages/  styles/
  public/
    figures/                      ← generated equation/figure/cover images (git-ignored)
```

### The extraction pipeline (`pipeline/extract.py`)

- Reads the PDF table of contents to build the chapter/section tree.
- Walks the pages in reading order and classifies each block as **prose**,
  **heading**, **caption**, **figure/table** or **display equation**.
- Cleans prose text: the thesis was authored in Word, whose equation export
  *doubles* every math glyph (`𝜃𝜃` → one `θ`) and linearises matrices. The cleaner
  de-doubles math letters, maps math Unicode to normal letters/Greek, and strips the
  broken layout glyphs — so inline math reads correctly **and is searchable**.
- Crops every display equation, figure and table to a high-resolution PNG (exact
  fidelity, no risky transcription) and saves the cover artwork for the hero.
- Emits `site/src/data/thesis.json` + images, and copies the PDF into `public/` for
  download.

### The site (`site/`)

- **Astro** static site, themed with the PDF's own palette (red `#C00000`, aviation
  blue `#2E75B6`/`#054697`, greys). One page per chapter with a sticky chapter/section
  sidebar, prev/next navigation, and the Constellation cover hero.
- **Pagefind** builds a client-side full-text index over the prose + captions at
  build time — instant search with no backend.
- Responsive (mobile drawer nav) and accessible (semantic headings, alt text on every
  figure, keyboard-navigable).

## Local development

Requires Node 20+ and Python 3.10+.

```bash
# 1. generate the content model + images from the PDF
cd site
npm install
npm run extract        # runs ../pipeline/extract.py (needs `pip install -r ../pipeline/requirements.txt`)

# 2. develop
npm run dev            # http://localhost:4321/angelo-tese

# 3. production build (Astro + Pagefind search index)
npm run build
npm run preview
```

> The content model (`src/data/thesis.json`) and images (`public/figures/`) are
> generated, so they are git-ignored. Run `npm run extract` once after cloning.

## Deployment

Pushing to `main` triggers `.github/workflows/deploy.yml`, which runs the extraction
pipeline, builds the Astro site + Pagefind index, and publishes to **GitHub Pages**.

**One-time setup:** in the repository settings, set **Pages → Build and deployment →
Source** to **GitHub Actions**. The site is then served at
`https://rockorama.github.io/angelo-tese/`.

Hosting elsewhere? Override the base path / domain at build time:

```bash
BASE_PATH=/ SITE_URL=https://example.com npm run build
```
