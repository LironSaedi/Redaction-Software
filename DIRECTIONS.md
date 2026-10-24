# Directions

Step-by-step instructions for working with this repository. For what Obscura does and how accurate it is, see
[README.md](README.md). For how the installers are built and signed, see [packaging/README.md](packaging/README.md).

## 1. Get the code

```bash
git clone git@github.com:LironSaedi/Redaction-Software.git "Redaction Software"
cd "Redaction Software"
```

The repository holds only the code. The AI models, the Python environment, build output, installers and case
data are kept out of Git on purpose, because they are large or private.

## 2. Install the tools (once per computer)

On macOS:

```bash
brew install uv node tesseract
```

On Windows, install [uv](https://docs.astral.sh/uv/), [Node.js](https://nodejs.org) and Tesseract (UB-Mannheim
build).

## 3. Set up the backend

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt --excludes requirements-exclude.txt
```

## 4. Get the AI models (about 4.6 GB)

Pick one:

- **Download once** (the only step that uses the internet):

  ```bash
  .venv/bin/python scripts/download_models.py
  ```

- **Use the copy on the Samsung T7:** plug in the drive and link it instead of downloading:

  ```bash
  ln -s /Volumes/T7/Obscura/models models
  ```

  On this Mac `backend/models` is already that link. **The T7 must be plugged in** whenever Obscura analyses
  files.

## 5. Build the web interface

```bash
cd ../frontend && npm ci && npm run build && cd ../backend
```

## 6. Run Obscura

```bash
.venv/bin/python -m obscura.main                    # http://127.0.0.1:8600, opens without sign-in on this computer
scripts/dev_server.sh --port 8610                    # development copy with a throwaway data folder in /tmp
```

## 7. Run the tests

```bash
.venv/bin/python -m pytest tests/unit -q             # about 2,700 fast tests, seconds
.venv/bin/python -m pytest tests -q                  # everything (about 20 minutes, uses the AI models)
cd ../frontend && npx vitest run && cd ../backend    # web interface tests
```

Accuracy benchmarks on the held-out documents:

```bash
.venv/bin/python benchmarks/run_heldout.py --split devall --cache-ml                       # legal / medical
.venv/bin/python benchmarks/run_heldout.py --split fin --profile financial --cache-ml      # financial
```

The sealed splits (`test`, `fintest`) print totals only. Never open those documents or tune against them.

## 8. Build the installers

- **macOS** (on an Apple Silicon Mac, from the repository folder):

  ```bash
  packaging/macos/build_macos.sh                   # → dist/Obscura-<version>-macOS.pkg (models not included)
  packaging/macos/build_macos.sh --with-models     # full offline installer
  ```

  On this Mac `build/` and `dist/` are links to the T7, so builds need the drive plugged in. Set
  `OBSCURA_BUILD_DIR` / `OBSCURA_DIST_DIR` to build somewhere else.

- **Windows:** run `packaging\windows\build_windows.ps1` on a Windows PC. Or use GitHub Actions:
  **Actions › installers › Run workflow**, then choose the platform and whether to include the models. From a
  terminal:

  ```bash
  gh workflow run installers.yml -f platform=windows -f with_models=false
  gh run watch
  ```

  The finished installers can be downloaded from the run's *Artifacts* section.

## 9. Save and push your changes

```bash
git status                                    # what changed
git add -A                                    # stage everything (.gitignore keeps models, data and builds out)
git commit -m "Describe what you changed"
git push                                      # sends it to GitHub (main)
```

Before pushing, check that `git status` doesn't list case documents, exported files, keys or anything from
`backend/data/`. The `.gitignore` excludes these, but a file copied in by hand somewhere else would not be
excluded.

To get changes made on another computer:

```bash
git pull
```
