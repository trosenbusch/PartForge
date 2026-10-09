/**
 * Vorschau-Bausteine: Symbol (SVG), Footprint (SVG), 3D (three.js, lazy) und das Panel mit allen drei Ansichten.
 *   import { PreviewPanel, SymbolCanvas, FootprintCanvas, Package3D } from '@/components/preview'
 */
export { CanvasBadge, CanvasTooltip, CanvasZoomControls } from './CanvasChrome'
export { CHROME_MUTED, CHROME_SURFACE } from './chrome'
export { FootprintCanvas, type FootprintCanvasProps } from './FootprintCanvas'
export { DEFAULT_LAYER_VISIBILITY, type LayerVisibility } from './layerVisibility'
export { footprintDimensions, type DimensionCallout, type DimensionLine, type FootprintDimensions } from './footprintDims'
export { IsoFallback } from './IsoFallback'
export { Package3D, type Package3DProps } from './Package3D'
export { PreviewPanel, type PreviewLayout, type PreviewPanelProps, type PreviewTab } from './PreviewPanel'
export { usePreviewPrefs, type PreviewPrefs } from './previewPrefs'
export { SymbolCanvas, type SymbolCanvasProps } from './SymbolCanvas'
export type { CanvasHandle, ChromeTone, SymbolCanvasTheme } from './types'
export { useElementSize } from './useElementSize'
export { gridStep, scaleBucket, usePanZoom, type PanZoom, type PanZoomOptions, type ViewState } from './usePanZoom'
export {
  previewKeys,
  useFootprintPreview,
  useSymbolPreview,
  type FootprintPreviewData,
  type SymbolPreviewData,
} from './usePreviewData'
export { isWebGLAvailable } from './webgl'
