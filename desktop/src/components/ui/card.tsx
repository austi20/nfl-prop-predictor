import { cva, type VariantProps } from 'class-variance-authority'
import type { HTMLAttributes } from 'react'

import { cn } from '../../lib/utils'

const cardVariants = cva(
  'rounded-3xl border border-white/10 bg-white/5 shadow-[0_20px_80px_rgba(0,0,0,0.18)] backdrop-blur-md',
  {
    variants: {
      tone: {
        default: '',
        accent:
          'border-emerald-400/20 bg-[linear-gradient(180deg,rgba(16,185,129,0.08),rgba(255,255,255,0.04))]',
      },
    },
    defaultVariants: {
      tone: 'default',
    },
  },
)

type CardProps = HTMLAttributes<HTMLDivElement> & VariantProps<typeof cardVariants>

export function Card({ className, tone, ...props }: CardProps) {
  return <div className={cn(cardVariants({ tone }), className)} {...props} />
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex flex-col gap-2 p-5 sm:p-6', className)} {...props} />
}

export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn('text-sm font-semibold uppercase tracking-[0.2em] text-slate-300', className)}
      {...props}
    />
  )
}

export function CardContent({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-5 pb-5 sm:px-6 sm:pb-6', className)} {...props} />
}
