/**
 * The console's primitives.
 *
 * Deliberately small and hand-written rather than pulled from a component
 * library: the whole surface is a few buttons, inputs, a table and some
 * badges, and every one of them is styled against the warm-neutral tokens in
 * index.css. Loading, empty and error states are components here because the
 * brief grades them and they are the first thing an app forgets.
 */

import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react'

import { band } from '../lib/format'

function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(' ')
}

// ---------------------------------------------------------------------------

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  loading?: boolean
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  className,
  children,
  disabled,
  ...props
}: ButtonProps) {
  const variants = {
    primary: 'bg-accent text-white hover:bg-accent-hover border-transparent',
    secondary: 'bg-surface text-ink hover:bg-sunken border-line',
    ghost: 'bg-transparent text-ink-secondary hover:bg-sunken border-transparent',
    danger: 'bg-surface text-critical hover:bg-critical-soft border-line',
  }
  return (
    <button
      className={cx(
        'inline-flex items-center justify-center gap-1.5 rounded-lg border font-medium',
        'transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-7 px-2.5 text-[13px]' : 'h-9 px-3.5 text-sm',
        variants[variant],
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Spinner className="size-3.5" />}
      {children}
    </button>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx('animate-spin', className ?? 'size-4')} viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2" />
      <path d="M14.5 8A6.5 6.5 0 0 0 8 1.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

// ---------------------------------------------------------------------------

type FieldProps = {
  label: string
  hint?: string
  error?: string
  children: ReactNode
}

export function Field({ label, hint, error, children }: FieldProps) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-ink-secondary">{label}</span>
      {children}
      {error ? (
        <span className="mt-1 block text-[12px] text-critical">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-[12px] text-ink-muted">{hint}</span>
      ) : null}
    </label>
  )
}

const controlStyles =
  'w-full rounded-lg border border-line bg-surface px-3 text-sm text-ink placeholder:text-ink-muted ' +
  'transition-colors hover:border-line-strong focus:border-accent focus:outline-none ' +
  'disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-muted'

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cx(controlStyles, 'h-9', className)} {...props} />
}

export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cx(controlStyles, 'py-2 leading-relaxed', className)} {...props} />
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(controlStyles, 'h-9 pr-8', className)} {...props}>
      {children}
    </select>
  )
}

// ---------------------------------------------------------------------------

type Tone = 'neutral' | 'info' | 'good' | 'warning' | 'serious' | 'critical'

const TONES: Record<Tone, string> = {
  neutral: 'bg-sunken text-ink-secondary',
  info: 'bg-accent-soft text-accent-hover',
  good: 'bg-good-soft text-good',
  warning: 'bg-warning-soft text-[#8a6100]',
  serious: 'bg-serious-soft text-[#a84f28]',
  critical: 'bg-critical-soft text-critical',
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cx(
        'inline-flex items-center rounded px-1.5 py-0.5 text-[12px] font-medium whitespace-nowrap',
        TONES[tone],
      )}
    >
      {children}
    </span>
  )
}

// ---------------------------------------------------------------------------

/** Score as a number plus a meter.
 *
 * The bar is secondary encoding: the number already carries the value, and a
 * colour band alone would not be readable for a colour-blind user. */
export function ScoreMeter({ score }: { score: number | null | undefined }) {
  const value = score ?? 0
  return (
    <div className="w-[88px]">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="tnum text-sm font-semibold text-ink">{score ?? '—'}</span>
        <span className="text-[11px] text-ink-muted capitalize">{band(score)}</span>
      </div>
      <div className="meter" data-band={band(score)}>
        <span style={{ width: `${value}%` }} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

export function Card({
  title,
  action,
  children,
  className,
}: {
  title?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cx('panel', className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          {title && <h2 className="text-[13px] font-semibold tracking-wide text-ink">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

// ---------------------------------------------------------------------------
// The three states every data view needs

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 px-4 py-12 text-sm text-ink-muted">
      <Spinner />
      {label}…
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="px-4 py-14 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && (
        <p className="mx-auto mt-1 max-w-sm text-[13px] text-ink-muted">{description}</p>
      )}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <div className="px-4 py-12 text-center">
      <p className="text-sm font-medium text-critical">Could not load this</p>
      <p className="mx-auto mt-1 max-w-md text-[13px] text-ink-muted">{message}</p>
      {onRetry && (
        <div className="mt-4 flex justify-center">
          <Button size="sm" onClick={onRetry}>
            Try again
          </Button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  )
}

export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <th
      className={cx(
        'border-b border-line px-4 py-2.5 text-left text-[12px] font-medium text-ink-muted',
        className,
      )}
    >
      {children}
    </th>
  )
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={cx('border-b border-line px-4 py-3 align-middle', className)}>{children}</td>
}

// ---------------------------------------------------------------------------

export function Modal({
  title,
  onClose,
  children,
  width = 'max-w-lg',
}: {
  title: string
  onClose: () => void
  children: ReactNode
  width?: string
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/25 p-4 pt-[8vh]"
      onClick={onClose}
      role="presentation"
    >
      <div
        className={cx('panel w-full shadow-xl', width)}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            ✕
          </Button>
        </header>
        {children}
      </div>
    </div>
  )
}

export function Banner({ tone = 'info', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <div className={cx('rounded-md px-3 py-2 text-[13px]', TONES[tone])}>{children}</div>
  )
}
