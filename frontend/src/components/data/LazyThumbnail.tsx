import { useI18n } from '@/lib/i18n'
import { useQuery } from '@tanstack/react-query'
import { ImageOff } from 'lucide-react'
import { useEffect, useId, useMemo, useState, type ReactNode } from 'react'
import { Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'

export interface LazyThumbnailProps {
  /** Fertige Bild-URL */
  src?: string
  /** SVG-Markup laden (gecacht unter `queryKey`; erstes Element = Modulname, z. B. ['footprints', 'thumb', name]) */
  loadSvg?: (signal: AbortSignal) => Promise<string>
  queryKey?: readonly unknown[]
  /** Eigener Inhalt, erst im Sichtbereich gerendert */
  render?: () => ReactNode
  alt?: string
  /** Abstand zum Rand (Vorladen) */
  rootMargin?: string
  className?: string
  /** Bildinnenabstand */
  inset?: string
}

function useInView<T extends Element>(rootMargin: string): [(el: T | null) => void, boolean] {
  const [node, setNode] = useState<T | null>(null)
  // ohne IntersectionObserver (alte Umgebungen) sofort laden
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    if (!node || seen) return
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true)
          io.disconnect()
        }
      },
      { rootMargin },
    )
    io.observe(node)
    return () => io.disconnect()
  }, [node, seen, rootMargin])
  return [setNode, seen]
}

function SvgBlobImage({ svg, alt, className }: { svg: string; alt: string; className?: string }) {
  useI18n()
  const url = useMemo(() => URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' })), [svg])
  useEffect(() => () => URL.revokeObjectURL(url), [url])
  return <FadeImage key={url} src={url} alt={alt} className={className} />
}

function FadeImage({ src, alt, className }: { src: string; alt: string; className?: string }) {
  useI18n()
  const [loaded, setLoaded] = useState(false)
  return (
    <img
      src={src}
      alt={alt}
      draggable={false}
      onLoad={() => setLoaded(true)}
      className={cn('size-full object-contain transition-opacity duration-300', loaded ? 'opacity-100' : 'opacity-0', className)}
    />
  )
}

export function LazyThumbnail({
  src,
  loadSvg,
  queryKey,
  render,
  alt = '',
  rootMargin = '200px',
  className,
  inset = 'p-3',
}: LazyThumbnailProps) {
  const { t: tr } = useI18n()
  const [ref, inView] = useInView<HTMLDivElement>(rootMargin)
  const id = useId()
  const q = useQuery({
    queryKey: queryKey ?? ['thumbnail', id],
    queryFn: ({ signal }) => (loadSvg ? loadSvg(signal) : Promise.resolve('')),
    enabled: inView && Boolean(loadSvg),
    staleTime: 10 * 60_000,
    gcTime: 10 * 60_000,
  })
  const [imgLoaded, setImgLoaded] = useState(false)

  let content: ReactNode = null
  if (inView) {
    if (render) content = render()
    else if (src)
      content = (
        <img
          src={src}
          alt={alt}
          draggable={false}
          loading="lazy"
          onLoad={() => setImgLoaded(true)}
          className={cn('size-full object-contain transition-opacity duration-300', imgLoaded ? 'opacity-100' : 'opacity-0')}
        />
      )
    else if (loadSvg) {
      if (q.isError)
        content = (
          <div className="flex size-full items-center justify-center text-fg-subtle" title={tr("Vorschau nicht verfügbar")}>
            <ImageOff aria-hidden className="size-5" />
          </div>
        )
      else if (q.data) content = <SvgBlobImage svg={q.data} alt={alt} />
    }
  }
  const pending = !inView || (loadSvg && !render && !src && q.isPending)
  return (
    <div ref={ref} className={cn('relative size-full', className)}>
      {pending && <Skeleton className="absolute inset-3 rounded-control opacity-60" />}
      {content && <div className={cn('absolute inset-0', inset)}>{content}</div>}
    </div>
  )
}
