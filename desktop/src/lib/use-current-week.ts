import { useQuery } from '@tanstack/react-query'

import { getSchedule } from './api'

/**
 * The week the season is actually on, from the schedule.
 *
 * Returns null until it loads. Callers gate their own query on that rather
 * than falling back to Week 1: a past week's Kalshi markets have settled, so
 * defaulting to 1 builds an empty board and caches it.
 */
export function useCurrentWeek(season: number): number | null {
  const { data } = useQuery({
    queryKey: ['schedule', season],
    queryFn: () => getSchedule(season),
    staleTime: 1000 * 60 * 60,
  })
  return data?.current_week ?? null
}
