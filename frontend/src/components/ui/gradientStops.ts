/**
 * Farbstopps der Verläufe „Schmiede“ (Kupfer) und „Funken“ (KI) für SVG-`<linearGradient>` – dieselben Tokens wie die
 * CSS-Verläufe (`--pf-forge-1…3`, `--pf-spark-1…3` in `styles/index.css`). Als `style={{ stopColor }}` setzen:
 * SVG-Attribute verstehen kein `var()`.
 */
export type GradientStop = readonly [offset: string, color: string]

export const FORGE_STOPS: readonly GradientStop[] = [
  ['0', 'var(--pf-forge-1)'],
  ['0.5', 'var(--pf-forge-2)'],
  ['1', 'var(--pf-forge-3)'],
]

export const SPARK_STOPS: readonly GradientStop[] = [
  ['0', 'var(--pf-spark-1)'],
  ['0.5', 'var(--pf-spark-2)'],
  ['1', 'var(--pf-spark-3)'],
]
