(() => {
  "use strict";

  // Applies the saved colour theme before the stylesheet paints, so switching
  // to the night theme on a later visit never flashes the light theme first.
  const STORAGE_KEY = "lucky-wheel-theme";
  const root = document.documentElement;

  function normalize(value) {
    return value === "night" ? "night" : "day";
  }

  function get() {
    return normalize(root.dataset.theme);
  }

  function apply(theme) {
    const next = normalize(theme);
    root.dataset.theme = next;
    return next;
  }

  function save(theme) {
    const next = normalize(theme);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private browsing or a blocked storage quota: the theme still applies
      // for this page load, it just will not be remembered.
    }
    return next;
  }

  function set(theme) {
    return save(apply(theme));
  }

  let saved = null;
  try {
    saved = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    saved = null;
  }
  apply(saved);

  window.WheelTheme = { storageKey: STORAGE_KEY, get, set };
})();
