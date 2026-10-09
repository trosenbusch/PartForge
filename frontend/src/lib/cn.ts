import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

/** tailwind-merge, erweitert um die PartForge-Tokens (Radien, Schatten, Schriftgrößen, Ebenen). */
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      radius: ['control', 'button', 'card', 'panel'],
      shadow: ['card', 'raised', 'pop', 'glow', 'glow-spark'],
      text: ['2xs', 'ui', 'md', 'metric', 'h1', 'h2', 'h3', 'display'],
    },
    classGroups: {
      z: [{ z: ['sticky', 'sidebar', 'dock', 'modal', 'popover', 'palette', 'tooltip', 'drop', 'skip'] }],
    },
  },
})

/** Klassen zusammenführen: clsx-Bedingungen + Konfliktauflösung von Tailwind-Klassen. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
