import { createBrowserRouter } from 'react-router-dom'

import App from './App'
import { DashboardPage } from './routes/dashboard-page'
import { ExecutionPage } from './routes/execution-page'
import { PlayerDetailPage } from './routes/player-detail-page'
import { ParlayBuilderPage } from './routes/parlay-builder-page'
import { RouteError } from './routes/route-error'
import { ThisWeekPage } from './routes/this-week-page'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    errorElement: <RouteError />,
    children: [
      {
        index: true,
        element: <ThisWeekPage />,
      },
      {
        path: 'player/:playerId',
        element: <PlayerDetailPage />,
      },
      {
        path: 'props',
        element: <DashboardPage />,
      },
      {
        path: 'parlays',
        element: <ParlayBuilderPage />,
      },
      {
        path: 'execution',
        element: <ExecutionPage />,
      },
    ],
  },
])
