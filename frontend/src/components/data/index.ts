/**
 * Daten-Bausteine: Kategoriebaum, Datei-Drop-Zone, teilbare Bereiche, virtualisierte Galerie, Vorlagen-Eingabe.
 *   import { CategoryTree, FileDropZone, SplitPane, VirtualGallery, TemplateTokenInput } from '@/components/data'
 */
export { CategoryIcon, type CategoryIconProps } from './CategoryIcon'
export { CategoryTree, type CategoryTreeItem, type CategoryTreeProps } from './CategoryTree'
export { CATEGORY_GROUP_ORDER, CATEGORY_GROUPS, categoryToTreeItem, useCategoryTreeItems } from './categoryTreeItems'
export { FileDropZone, type FileDropTone, type FileDropVariant, type FileDropZoneProps } from './FileDropZone'
export { GalleryCard, type GalleryCardProps } from './GalleryCard'
export { LazyThumbnail, type LazyThumbnailProps } from './LazyThumbnail'
export { SplitPane, type SplitPaneProps } from './SplitPane'
export {
  TemplateTokenInput,
  type TemplateField,
  type TemplateFormat,
  type TemplateTokenInputProps,
} from './TemplateTokenInput'
export { buildToken, parseTemplate, TEMPLATE_FORMATS, templateFields, tokenAt, type TemplateSegment } from './templateTokens'
export { VirtualGallery, type GalleryItemState, type VirtualGalleryProps } from './VirtualGallery'
