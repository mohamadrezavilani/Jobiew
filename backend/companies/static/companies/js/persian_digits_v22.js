/* Workplace Insights v22: visual-only digit normalization for Persian UI.
 * 0-9 and U+0660-U+0669 -> U+06F0-U+06F9 in user-facing DOM.
 * No numeric data, URL, element value, scripts, JSON or CSS is modified.
 */
(function () {
  'use strict';
  const fa = '۰۱۲۳۴۵۶۷۸۹';
  const excluded = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'CODE', 'PRE', 'TEXTAREA', 'OPTION']);
  const attrs = ['title', 'aria-label', 'aria-valuetext', 'placeholder'];
  function digits(text) {
    return text.replace(/[0-9\u0660-\u0669]/g, function (char) {
      const code = char.charCodeAt(0);
      return fa[code >= 0x0660 ? code - 0x0660 : code - 48];
    });
  }
  function excludedNode(node) {
    let el = node.nodeType === 1 ? node : node.parentElement;
    while (el) {
      if (excluded.has(el.tagName) || el.hasAttribute('data-persian-digits-skip') || el.isContentEditable) {
        return true;
      }
      el = el.parentElement;
    }
    return false;
  }
  function fixText(node) {
    if (excludedNode(node)) return;
    const before = node.nodeValue;
    const after = digits(before);
    if (after !== before) node.nodeValue = after;
  }
  function fixAttributes(el) {
    if (excludedNode(el)) return;
    attrs.forEach(function (attr) {
      if (!el.hasAttribute(attr)) return;
      const before = el.getAttribute(attr);
      const after = digits(before);
      if (after !== before) el.setAttribute(attr, after);
    });
  }
  function scan(root) {
    if (root.nodeType === 3) { fixText(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1) {
      if (excludedNode(root)) return;
      fixAttributes(root);
    }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let current;
    while ((current = walker.nextNode())) {
      if (current.nodeType === 3) fixText(current);
      else fixAttributes(current);
    }
  }
  function start() {
    scan(document);
    // The internal charts create text and SVG tooltips dynamically.
    // Observe only rendered changes, not data attributes or input values.
    const observer = new MutationObserver(function (records) {
      records.forEach(function (record) {
        if (record.type === 'characterData') fixText(record.target);
        else record.addedNodes.forEach(scan);
      });
    });
    observer.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
