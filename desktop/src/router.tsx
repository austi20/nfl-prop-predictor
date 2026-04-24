import { createBrowserRouter } from 'react-router-dom'

import App from './App'
import { DashboardPage } from './routes/dashboard-page'
import { PlayerDetailPage } from './routes/player-detail-page'
import { ParlayBuilderPage } from './routes/parlay-builder-page'
import { RouteError } from './routes/route-error'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    errorElement: <RouteError />,
    children: [
      {
        index: true,
        element: <DashboardPage />,
      },
      {
        path: 'player/:playerId',
        element: <PlayerDetailPage />,
      },
      {
        path: 'parlays',
        element: <ParlayBuilderPage />,
      },
    ],
  },
])
