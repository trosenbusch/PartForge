import { useCallback, useLayoutEffect, useRef, useState } from 'react'

export interface ElementSize {
  width: number
  height: number
}

/**
 * Größe eines Elements (ResizeObserver, gerundet auf ganze Pixel). Gibt einen Ref-Callback und die Größe zurück;
 * vor der ersten Messung ist die Größe 0 × 0.
 */
export function useElementSize<T extends HTMLElement = HTMLDivElement>(): [(node: T | null) => void, ElementSize, T | null] {
  const [node, setNode] = useState<T | null>(null)
  const [size, setSize] = useState<ElementSize>({ width: 0, height: 0 })
  const frame = useRef(0)

  useLayoutEffect(() => {
    if (!node) return
    const measure = () => {
      const rect = node.getBoundingClientRect()
      const width = Math.round(rect.width)
      const height = Math.round(rect.height)
      setSize((s) => (s.width === width && s.height === height ? s : { width, height }))
    }
    measure()
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(frame.current)
      frame.current = requestAnimationFrame(measure)
    })
    ro.observe(node)
    return () => {
      cancelAnimationFrame(frame.current)
      ro.disconnect()
    }
  }, [node])

  const ref = useCallback((el: T | null) => setNode(el), [])
  return [ref, size, node]
}
