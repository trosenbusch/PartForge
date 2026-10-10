declare module 'occt-import-js' {
  const createImporter: (options: {
    locateFile: (path: string) => string
    print?: (text: string) => void
    printErr?: (text: string) => void
  }) => Promise<import('./stepTypes').OcctImporter>
  export default createImporter
}
