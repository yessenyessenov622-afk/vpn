(() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  const initData = tg && tg.initData ? tg.initData : "";
  const preview = !initData;
  const supported = code => Object.prototype.hasOwnProperty.call(translations, code);
  let language = "ru", modeKey = preview ? "preview" : "", statusKey = "", error = false, busy = false, ready = preview;
  const mode = document.getElementById("mode"), status = document.getElementById("status"), list = document.getElementById("languages");
  if (tg) { tg.ready(); tg.expand(); }

  function render() {
    const strings = translations[language];
    document.documentElement.lang = language;
    document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = strings[el.dataset.i18n]; });
    document.querySelectorAll("[data-i18n-aria]").forEach(el => { el.setAttribute("aria-label", strings[el.dataset.i18nAria]); });
    mode.hidden = !modeKey;
    mode.textContent = modeKey ? strings[modeKey] : "";
    status.textContent = statusKey ? strings[statusKey] : "";
    status.classList.toggle("error", error);
    list.replaceChildren();
    Object.keys(translations).forEach(code => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-pressed", String(code === language));
      button.disabled = busy || !ready;
      button.textContent = translations[code].name + (code === language ? " ✓" : "");
      button.addEventListener("click", () => choose(code));
      list.appendChild(button);
    });
  }
  async function choose(code) {
    const previous = language;
    language = code; statusKey = ""; error = false; busy = true; render();
    try {
      if (preview) {
        localStorage.setItem("vpn-preview-language", code);
        statusKey = "localSaved";
      } else {
        const response = await fetch("/api/settings", {method:"PUT", headers:{"Content-Type":"application/json", "X-Telegram-Init-Data":initData}, body:JSON.stringify({language:code})});
        if (!response.ok) throw new Error("save failed");
        statusKey = "saved";
      }
    } catch (_) { language = previous; statusKey = "saveError"; error = true; }
    finally { busy = false; render(); }
  }
  document.querySelectorAll("[data-tab]").forEach(button => button.addEventListener("click", () => {
    document.querySelectorAll("[data-tab]").forEach(item => item.setAttribute("aria-selected", String(item === button)));
    document.getElementById("home").hidden = button.dataset.tab !== "home";
    document.getElementById("settings").hidden = button.dataset.tab !== "settings";
  }));
  if (preview) {
    try { const stored = localStorage.getItem("vpn-preview-language"); if (supported(stored)) language = stored; } catch (_) { /* Browser storage may be unavailable. */ }
    render();
  } else {
    render();
    fetch("/api/settings", {headers:{"X-Telegram-Init-Data":initData}})
      .then(response => { if (!response.ok) throw new Error("load failed"); return response.json(); })
      .then(data => { if (supported(data.language)) language = data.language; ready = true; })
      .catch(() => { modeKey = "loadError"; })
      .finally(render);
  }
})();
