/** Gemeinsame Klassen für DropdownMenu, ContextMenu und Select-Listen. */
export const menuContentClass =
  'pop-anim glass z-popover min-w-[13rem] overflow-hidden rounded-card p-1 text-fg outline-none'

export const menuItemClass = [
  'relative flex h-8 cursor-default select-none items-center gap-2.5 rounded-control px-2 text-ui text-fg outline-none',
  'transition-colors duration-75',
  'data-[highlighted]:bg-[color-mix(in_oklab,var(--pf-fg)_8%,transparent)]',
  'data-[disabled]:pointer-events-none data-[disabled]:opacity-45',
  '[&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-fg-muted data-[highlighted]:[&_svg]:text-fg',
].join(' ')

export const menuItemDangerClass =
  'text-danger-text [&_svg]:text-danger-text data-[highlighted]:bg-danger/12 data-[highlighted]:text-danger-text data-[highlighted]:[&_svg]:text-danger-text'

export const menuLabelClass = 'micro-label px-2 pb-1 pt-2'

export const menuSeparatorClass = 'mx-1 my-1 h-px bg-line'

export const menuIndicatorClass = 'ml-auto flex size-4 items-center justify-center text-accent'
