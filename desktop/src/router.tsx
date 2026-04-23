import { createBrowserRouter } from 'react-router-dom'

import App from './App'
import { dashboardLoader } from './routes/dashboard-loader'
import { DashboardPage } from './routes/dashboard-page'
import { playerDetailLoader } from './routes/player-detail-loader'
import { PlayerDetailPage } from './routes/player-detail-page'
import { ParlayBuilderPage } from './routes/parlay-builder-page'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      {
        index: true,
        loader: dashboardLoader,
        element: <DashboardPage />,
      },
      {
        path: 'player/:playerId',
        loader: playerDetailLoader,
        element: <PlayerDetailPage />,
      },
      {
        path: 'parlays',
        loader: dashboardLoader,
        element: <ParlayBuilderPage />,
      },
    ],
  },
])
