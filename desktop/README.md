# NFL Prop Predictor — Desktop

Tauri 2 + React 19 desktop app wrapping the FastAPI sidecar. Fantasy-first:
the landing page is the ranked weekly fantasy board; props and paper trading
are secondary tabs.

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

The sidecar binary (`binaries/nfl-prop-api-x86_64-pc-windows-msvc.exe`) must be built first:

```powershell
# from repo root
.\desktop\scripts\build-sidecar.ps1
```

## Routes

| Path | Page |
|------|------|
| `/` | This Week — ranked weekly fantasy board (proj / floor / ceiling / boom%) |
| `/props` | Props dashboard — slate + KPI cards + decision drawer |
| `/parlays` | Parlay builder |
| `/execution` | Trading (Paper) — execution + portfolio + audit |
| `/player/:playerId` | Player detail + analyst panel |
