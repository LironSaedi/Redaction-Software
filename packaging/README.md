# Installers

Obscura ships as a normal desktop install for **macOS (Apple Silicon)** and **Windows 10/11 (x64)**.
Everything the app needs comes inside the installer: its own Python, the web interface, the OCR engine and, in the
"full" build, the AI models. Nothing has to be installed first. Nothing is downloaded after installation unless
you choose to download the models in the setup assistant.

| | macOS | Windows |
|---|---|---|
| Installer | `Obscura-<v>-macOS.pkg`: standard macOS Installer wizard | `Obscura-<v>-Windows.exe`: Inno Setup wizard |
| Installs to | `Applications/Obscura/` (all users) or `~/Applications/Obscura/` ("Install for me only", no admin password) | `%LOCALAPPDATA%\Programs\Obscura` (no admin password) or Program Files (choose "all users") |
| Start | Obscura in Applications / Launchpad | Start menu › Obscura (optional desktop icon) |
| Settings and data | `~/Library/Application Support/Obscura/` | `%LOCALAPPDATA%\Obscura\` |
| Uninstall | "Uninstall Obscura" app in the same folder, the app's **Uninstall…** link, or System page › Uninstall | Settings › Apps › Obscura Redaction Studio, Start menu › Uninstall Obscura, or the app's Uninstall button |

Every uninstall path asks whether to **keep or delete the case files**. Keeping them is the default, so a reinstall
finds them again. Deleting removes the encryption keys first, so any fragment left on disk can't be decrypted.

## First run

Opening Obscura shows a small control window: **Open Obscura**, **Stop and quit**, **Open data folder** and
**Uninstall…**. The setup assistant then opens in the browser:

1. **How will you use it?**
   - *Just this computer*: no sign-in.
   - *Office server*: colleagues open `http://<this computer>:8600` and sign in; you create the administrator here.
2. **Where to keep case files**: uses the computer's own folder picker. Files are encrypted with AES-256.
3. **AI models**: already included (full installer), *import from a folder / USB drive*, or *download once*.
   Downloading fetches only model files from their publishers; no documents or settings are sent.
4. **Start at login** (optional).

## Building

| | macOS | Windows |
|---|---|---|
| Machine | Apple Silicon Mac with Xcode command line tools, `uv`, `brew install tesseract`, Node.js | Windows with `uv`, Node.js, Inno Setup 6 (`winget install JRSoftware.InnoSetup`) |
| Program only | `packaging/macos/build_macos.sh` | `powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1` |
| Full offline | `packaging/macos/build_macos.sh --with-models` | `… build_windows.ps1 -WithModels` |
| Output | `dist/*.pkg` | `dist/Obscura-*-Windows*.exe` (the full build adds `.bin` parts, because it is larger than 4 GB) |

Builds need about 4 GB of working space (9 GB with models). To keep that off the main disk, set
`OBSCURA_BUILD_DIR` and `OBSCURA_DIST_DIR`, or make `build/` and `dist/` links to another drive. On this
machine they point to the Samsung T7 (`/Volumes/T7/Obscura`), and the build stops with a clear message when
that drive is not connected.

The full builds need the models in `backend/models` first (`backend/scripts/download_models.py`). Alternatively, run
the **installers** workflow in GitHub Actions (`.github/workflows/installers.yml`), which builds both.

### Signing

- **macOS:** unsigned builds work, but Gatekeeper asks once (right-click › Open). To distribute widely, set:

  ```
  SIGN_APP="Developer ID Application: …"
  SIGN_PKG="Developer ID Installer: …"
  NOTARY_PROFILE=<xcrun notarytool keychain profile>
  ```

- **Windows:** unsigned installers show SmartScreen's "More info › Run anyway". Pass `-SignTool "signtool sign /fd sha256 /a /tr <timestamp-url> /td sha256"` to sign.

### Licences to check before distributing outside your organisation

PyMuPDF and Ultralytics YOLO are AGPL-3.0. Using them inside your firm is fine. Giving the installer to other
organisations requires either AGPL compliance (offering the source) or commercial licences from Artifex (PyMuPDF)
and Ultralytics. The NVIDIA gliner-PII model is under the NVIDIA Open Model License. All licence texts are copied
into the install (`licenses/`).
