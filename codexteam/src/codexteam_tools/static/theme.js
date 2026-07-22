(() => {
  const key = "codexteam-theme";
  const allowed = new Set(["system", "light", "dark"]);
  const stored = localStorage.getItem(key);
  const theme = allowed.has(stored) ? stored : "system";

  function apply(value) {
    if (value === "system") {
      delete document.documentElement.dataset.theme;
      document.documentElement.style.colorScheme = "light dark";
    } else {
      document.documentElement.dataset.theme = value;
      document.documentElement.style.colorScheme = value;
    }
  }

  apply(theme);
  window.addEventListener("DOMContentLoaded", () => {
    const select = document.getElementById("theme-select");
    select.value = theme;
    select.addEventListener("change", () => {
      localStorage.setItem(key, select.value);
      apply(select.value);
    });
  });
})();
