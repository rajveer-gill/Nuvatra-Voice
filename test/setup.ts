import '@testing-library/jest-dom/vitest'

// jsdom doesn't implement the native <dialog> API that some components use
// (StructuredListEditors calls showModal()/close()). Polyfill minimally so
// those components mount without throwing.
if (typeof HTMLDialogElement !== 'undefined') {
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.open = true
  }
  HTMLDialogElement.prototype.close = function close() {
    this.open = false
  }
}

// jsdom doesn't implement scrollIntoView; components call it on refs (e.g. the
// Settings save bar). No-op it so those effects don't throw mid-render.
if (typeof Element !== 'undefined' && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {}
}
