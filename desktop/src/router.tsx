import { createBrowserRouter } from 'react-router-dom'

import App from './App'
import { dashboardLoader } from './routes/dashboard-loader'
import { DashboardPage } from './routes/dashboard-page'
import { playerDetailLoader } from './routes/player-detail-loader'
import { PlayerDetailPage } from './routes/player-detail-page'
import { ParlayBuilderPage } from './routes/parlay-builder-page'
import { RouteError } from './routes/route-error'
import { RouteLoadingFallback } from './routes/route-loading-fallback'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    errorElement: <RouteError />,
    // Avoid a blank <Outlet/> while API wait + slate/player loaders run (React Router 7).
    hydrateFallbackElement: <RouteLoadingFallback message="Starting app…" />,
    children: [
      {
        index: true,
        loader: dashboardLoader,
        element: <DashboardPage />,
        hydrateFallbackElement: <RouteLoadingFallback message="Loading slate…" />,
      },
      {
        path: 'player/:playerId',
        loader: playerDetailLoader,
        element: <PlayerDetailPage />,
        hydrateFallbackElement: <RouteLoadingFallback message="Loading player…" />,
      },
      {
        path: 'parlays',
        loader: dashboardLoader,
        element: <ParlayBuilderPage />,
        hydrateFallbackElement: <RouteLoadingFallback message="Loading builder…" />,
      },
    ],
  },
])
