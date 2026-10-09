import { animate, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'

/** Zahl animiert hochzählen (respektiert „Bewegung reduzieren“). */
export function useCountUp(target: number, duration = 0.9): number {
  const reduce = useReducedMotion()
  const [display, setDisplay] = useState(0)
  const fromRef = useRef(0)

  useEffect(() => {
    if (reduce) return
    const controls = animate(fromRef.current, target, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => {
        fromRef.current = v
        setDisplay(v)
      },
    })
    return () => controls.stop()
  }, [target, duration, reduce])

  return reduce ? target : display
}
