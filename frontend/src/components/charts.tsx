/**
 * Charts, built in plain SVG against fixed mark specs.
 *
 * The specs are not stylistic preferences — they are what keeps a set of
 * charts reading as one system: bars capped at 24px so the band keeps its air,
 * a 4px rounded data-end squared off at the baseline, a 2px surface gap doing
 * the separating instead of a stroke, hairline recessive gridlines, and labels
 * placed selectively rather than on every mark.
 *
 * Both charts plot a single ordered measure, so each uses one hue stepped
 * light-to-dark rather than a categorical palette: the steps carry magnitude,
 * which is the data's actual job. A single-series chart needs no legend — the
 * title already says what is plotted.
 */

import { useId, useState } from 'react'

/** Blue, light→dark. Validated as an ordinal ramp against the light surface:
 *  monotone lightness, visible step gaps, and the lightest step still clears
 *  2:1 so it does not dissolve into the panel. */
const RAMP = ['#86b6ef', '#5598e7', '#2a78d6', '#184f95']

const SURFACE = '#fcfcfb'
const GRID = '#e4e3dd'
const INK_MUTED = '#898781'
const INK = '#0b0b0b'

function stepFor(index: number, total: number): string {
  if (total <= 1) return RAMP[2]
  // Spread the available steps across however many marks there are, so a
  // three-stage and a five-stage chart both run the full ramp.
  const position = index / (total - 1)
  return RAMP[Math.min(RAMP.length - 1, Math.round(position * (RAMP.length - 1)))]
}

type Datum = { label: string; value: number; hint?: string }

// ---------------------------------------------------------------------------

export function FunnelChart({ data, caption }: { data: Datum[]; caption?: string }) {
  const [hovered, setHovered] = useState<number | null>(null)
  const max = Math.max(...data.map((d) => d.value), 1)

  return (
    <figure className="m-0">
      <ul className="space-y-2.5">
        {data.map((datum, index) => {
          const width = (datum.value / max) * 100
          const previous = index > 0 ? data[index - 1].value : null
          // Stage-to-stage conversion is the number a salesperson actually
          // reads a funnel for, so it is shown rather than left to arithmetic.
          const rate =
            previous && previous > 0 ? Math.round((datum.value / previous) * 100) : null

          return (
            <li
              key={datum.label}
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered(null)}
              className="relative"
            >
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <span className="text-[12px] text-ink-secondary">{datum.label}</span>
                <span className="flex items-baseline gap-2">
                  {rate !== null && (
                    <span className="text-[11px] text-ink-muted">{rate}% of previous</span>
                  )}
                  <span className="text-[13px] font-semibold text-ink">{datum.value}</span>
                </span>
              </div>

              <div className="h-3 w-full rounded-sm bg-sunken">
                <div
                  className="h-3 rounded-r-[4px] transition-[width,opacity] duration-300"
                  style={{
                    width: `${Math.max(width, datum.value > 0 ? 2 : 0)}%`,
                    background: stepFor(index, data.length),
                    opacity: hovered === null || hovered === index ? 1 : 0.55,
                  }}
                />
              </div>

              {hovered === index && datum.hint && (
                <div
                  role="tooltip"
                  className="absolute top-full left-0 z-10 mt-1 rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink shadow-sm"
                >
                  {datum.hint}
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {caption && (
        <figcaption className="mt-3 text-[12px] text-ink-muted">{caption}</figcaption>
      )}
    </figure>
  )
}

// ---------------------------------------------------------------------------

export function ColumnChart({
  data,
  caption,
  height = 150,
}: {
  data: Datum[]
  caption?: string
  height?: number
}) {
  const clipId = useId()
  const [hovered, setHovered] = useState<number | null>(null)

  const max = Math.max(...data.map((d) => d.value), 1)
  // Round the ceiling up to something a person would write on an axis.
  const ceiling = niceCeiling(max)

  const width = 320
  const padding = { top: 8, right: 8, bottom: 26, left: 30 }
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom
  const band = plotWidth / data.length
  // Capped rather than filling the band: the leftover is the air that keeps
  // columns from reading as a solid block. The 2px gap is the separator.
  const barWidth = Math.min(24, band - 10)

  const ticks = [0, ceiling / 2, ceiling]

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height }}
        role="img"
        aria-label={caption ?? 'Distribution'}
      >
        <defs>
          <clipPath id={clipId}>
            <rect x={padding.left} y={padding.top} width={plotWidth} height={plotHeight} />
          </clipPath>
        </defs>

        {ticks.map((tick) => {
          const y = padding.top + plotHeight - (tick / ceiling) * plotHeight
          return (
            <g key={tick}>
              {/* Hairline, solid, one step off surface — present but recessive. */}
              <line
                x1={padding.left}
                x2={width - padding.right}
                y1={y}
                y2={y}
                stroke={GRID}
                strokeWidth={1}
              />
              <text
                x={padding.left - 6}
                y={y + 3}
                textAnchor="end"
                fontSize={10}
                fill={INK_MUTED}
                style={{ fontVariantNumeric: 'tabular-nums' }}
              >
                {tick}
              </text>
            </g>
          )
        })}

        <g clipPath={`url(#${clipId})`}>
          {data.map((datum, index) => {
            const barHeight = (datum.value / ceiling) * plotHeight
            const x = padding.left + index * band + (band - barWidth) / 2
            const y = padding.top + plotHeight - barHeight
            const active = hovered === null || hovered === index

            return (
              <g key={datum.label}>
                {/* Drawn as a rounded rect overlaid by a square-cornered one at
                    the baseline: the data-end is rounded, the baseline is not. */}
                <rect
                  x={x}
                  y={y}
                  width={barWidth}
                  height={Math.max(barHeight, datum.value > 0 ? 3 : 0)}
                  rx={4}
                  fill={stepFor(index, data.length)}
                  opacity={active ? 1 : 0.55}
                  style={{ transition: 'opacity 150ms' }}
                />
                {barHeight > 4 && (
                  <rect
                    x={x}
                    y={y + barHeight - 4}
                    width={barWidth}
                    height={4}
                    fill={stepFor(index, data.length)}
                    opacity={active ? 1 : 0.55}
                  />
                )}
              </g>
            )
          })}
        </g>

        {/* The value rides the cap of the hovered column only — a number on
            every column is chaos and goes unread. */}
        {data.map((datum, index) => {
          const barHeight = (datum.value / ceiling) * plotHeight
          const x = padding.left + index * band + band / 2
          return (
            <g key={datum.label}>
              {hovered === index && (
                <text
                  x={x}
                  y={padding.top + plotHeight - barHeight - 5}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={600}
                  fill={INK}
                >
                  {datum.value}
                </text>
              )}
              <text
                x={x}
                y={height - 8}
                textAnchor="middle"
                fontSize={10}
                fill={hovered === index ? INK : INK_MUTED}
              >
                {datum.label}
              </text>
              {/* Hit target spans the whole band, not just the mark. */}
              <rect
                x={padding.left + index * band}
                y={padding.top}
                width={band}
                height={plotHeight}
                fill="transparent"
                onMouseEnter={() => setHovered(index)}
                onMouseLeave={() => setHovered(null)}
              >
                <title>{`${datum.label}: ${datum.value}`}</title>
              </rect>
            </g>
          )
        })}

        <line
          x1={padding.left}
          x2={width - padding.right}
          y1={padding.top + plotHeight}
          y2={padding.top + plotHeight}
          stroke={GRID}
          strokeWidth={1}
        />
      </svg>
      {caption && <figcaption className="mt-1 text-[12px] text-ink-muted">{caption}</figcaption>}
    </figure>
  )
}

function niceCeiling(value: number): number {
  if (value <= 5) return 5
  const magnitude = 10 ** Math.floor(Math.log10(value))
  return Math.ceil(value / magnitude) * magnitude
}

// ---------------------------------------------------------------------------

/** A single ratio against a limit. The unfilled track is a lighter step of the
 *  fill's own ramp, so the state reads across the whole bar. */
export function Meter({ value, max = 100 }: { value: number; max?: number }) {
  const ratio = Math.max(0, Math.min(1, value / max))
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: '#e4edfa' }}>
      <div
        className="h-full rounded-full transition-[width] duration-300"
        style={{ width: `${ratio * 100}%`, background: RAMP[2] }}
      />
    </div>
  )
}

export { RAMP as ORDINAL_RAMP, SURFACE as CHART_SURFACE }
