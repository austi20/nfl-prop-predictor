import { createBrowserRouter } from 'react-router-dom'

import App from './App'
import { dashboardLoader } from './routes/dashboard-loader'
import { DashboardPage } from './routes/dashboard-page'

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
    ],
  },
])
