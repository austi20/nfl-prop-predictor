# NFL Prop Workstation — Desktop

Tauri 2 + React desktop app wrapping the FastAPI sidecar.

## Dev

```
cd desktop
npm install
npm run tauri dev
```

The sidecar starts automatically on an ephemeral port. The React dev server runs on `http://localhost:5173`.

## Build

```
npm run tauri build
```

Produces an `.msi` installer in `src-tauri/target/release/bundle/msi/`.

The sidecar binary (`binaries/nfl-prop-api.exe`) must be built first:

```powershell
# from repo root
.\scripts\build-sidecar.ps1
```

## Routes

| Path | Page |
|------|------|
| `/` | Dashboard — slate + KPI cards |
| `/player/:playerId` | Player detail + analyst panel |
| `/parlays` | Parlay builder |
