(() => {
  const pageSelector = "main.page";
  const headerSelector = ".site-header";
  let visitController = null;

  function sameOriginUrl(value, base = window.location.href) {
    try {
      const url = new URL(value, base);
      return url.origin === window.location.origin ? url : null;
    } catch (error) {
      return null;
    }
  }

  function isHtmlResponse(response) {
    const contentType = response.headers.get("content-type") || "";
    return contentType.includes("text/html");
  }

  function isAttachmentResponse(response) {
    const disposition = response.headers.get("content-disposition") || "";
    return disposition.toLowerCase().includes("attachment");
  }

  function setBusy(isBusy) {
    document.documentElement.classList.toggle("ajax-busy", isBusy);
    document.documentElement.setAttribute("aria-busy", isBusy ? "true" : "false");
  }

  function activeUploadAllowsNavigation() {
    if (document.documentElement.dataset.uploadInProgress !== "true") return true;
    return window.confirm("An upload is still running. Leave this page anyway?");
  }

  function showInlineMessage(text, level = "error") {
    const main = document.querySelector(pageSelector);
    if (!main) return;
    let messages = main.querySelector(".messages");
    if (!messages) {
      messages = document.createElement("div");
      messages.className = "messages";
      main.prepend(messages);
    }
    const message = document.createElement("div");
    message.className = `message ${level}`;
    message.textContent = text;
    messages.prepend(message);
  }

  function executeScripts(root) {
    for (const script of root.querySelectorAll("script")) {
      const fresh = document.createElement("script");
      for (const attribute of script.attributes) {
        fresh.setAttribute(attribute.name, attribute.value);
      }
      fresh.textContent = script.textContent;
      script.replaceWith(fresh);
    }
  }

  function closeOpenMenus() {
    for (const details of document.querySelectorAll("details[open]")) {
      details.open = false;
    }
  }

  function setNavOpen(isOpen) {
    document.body.classList.toggle("nav-open", isOpen);
    const toggle = document.querySelector(".nav-toggle");
    if (toggle) {
      toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    }
  }

  function closeNav() {
    setNavOpen(false);
  }

  function swapShell(html, url, { push = false } = {}) {
    const parser = new DOMParser();
    const nextDocument = parser.parseFromString(html, "text/html");
    const nextMain = nextDocument.querySelector(pageSelector);
    const nextHeader = nextDocument.querySelector(headerSelector);
    const currentMain = document.querySelector(pageSelector);
    const currentHeader = document.querySelector(headerSelector);

    if (!nextMain || !currentMain) {
      window.location.assign(url);
      return;
    }

    if (nextDocument.title) {
      document.title = nextDocument.title;
    }

    if (nextHeader && currentHeader) {
      currentHeader.replaceWith(document.importNode(nextHeader, true));
    }

    currentMain.replaceWith(document.importNode(nextMain, true));
    document.documentElement.dataset.uploadInProgress = "false";
    if (window.ParafilesUploadState) {
      window.ParafilesUploadState.inProgress = false;
    }
    closeOpenMenus();
    closeNav();
    executeScripts(document.querySelector(pageSelector));

    if (url && url !== window.location.href) {
      if (push) {
        window.history.pushState({ parafilesAjax: true }, "", url);
      } else {
        window.history.replaceState({ parafilesAjax: true }, "", url);
      }
    }

    const main = document.querySelector(pageSelector);
    if (main) {
      main.setAttribute("tabindex", "-1");
      main.focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: "auto" });
    }

    document.dispatchEvent(new CustomEvent("parafiles:page-load", { detail: { url } }));
  }

  async function fetchHtml(url, options = {}) {
    if (visitController) {
      visitController.abort();
    }
    const controller = new AbortController();
    visitController = controller;
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "text/html, */*;q=0.8");
    headers.set("X-Parafiles-Ajax", "1");
    return fetch(url, {
      ...options,
      headers,
      signal: controller.signal,
      credentials: "same-origin",
    });
  }

  async function visit(url, { push = true } = {}) {
    const target = sameOriginUrl(url);
    if (!target || !activeUploadAllowsNavigation()) return false;
    setBusy(true);
    try {
      const response = await fetchHtml(target.href);
      if (isAttachmentResponse(response) || !isHtmlResponse(response)) {
        window.location.assign(target.href);
        return true;
      }
      const html = await response.text();
      swapShell(html, response.url || target.href, { push });
      return true;
    } catch (error) {
      if (error.name !== "AbortError") {
        showInlineMessage("The page could not be loaded. Please try again.");
      }
      return false;
    } finally {
      setBusy(false);
    }
  }

  function shouldSkipLink(link, event) {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return true;
    }
    if (link.target && link.target !== "_self") return true;
    if (link.hasAttribute("download")) return true;
    if (link.dataset.ajax === "off") return true;
    const url = sameOriginUrl(link.href);
    if (!url) return true;
    return (
      url.pathname === window.location.pathname &&
      url.search === window.location.search &&
      url.hash
    );
  }

  function revealHashTarget(url) {
    if (
      url.pathname !== window.location.pathname ||
      url.search !== window.location.search ||
      !url.hash
    ) {
      return false;
    }
    const targetId = decodeURIComponent(url.hash.slice(1));
    const target = document.getElementById(targetId);
    if (!target) return false;
    window.history.pushState({ parafilesAjax: true }, "", url.href);
    target.classList.add("is-revealed");
    target.scrollIntoView({ block: "start", behavior: "smooth" });
    return true;
  }

  function shouldSkipForm(form) {
    if (form.dataset.ajax === "off" || form.dataset.nativeSubmit !== undefined) return true;
    if (form.target && form.target !== "_self") return true;
    if (form.querySelector('input[type="file"]')) return true;
    const method = (form.method || "get").toLowerCase();
    if (method !== "get" && method !== "post") return true;
    const actionUrl = sameOriginUrl(form.action || window.location.href);
    if (!actionUrl) return true;
    if (actionUrl.pathname.startsWith("/download/prepare/")) return true;
    return false;
  }

  function formDataFor(form, submitter) {
    try {
      return submitter ? new FormData(form, submitter) : new FormData(form);
    } catch (error) {
      const data = new FormData(form);
      if (submitter && submitter.name && !submitter.disabled) {
        data.append(submitter.name, submitter.value);
      }
      return data;
    }
  }

  function urlWithFormData(actionUrl, data) {
    const url = new URL(actionUrl.href);
    url.search = "";
    for (const [key, value] of data.entries()) {
      if (typeof value === "string") {
        url.searchParams.append(key, value);
      }
    }
    return url;
  }

  async function submitForm(form, submitter) {
    if (!activeUploadAllowsNavigation()) return;
    const method = (form.method || "get").toLowerCase();
    const actionUrl = sameOriginUrl(form.action || window.location.href);
    const data = formDataFor(form, submitter);
    const buttons = [...form.querySelectorAll("button, input[type='submit']")];

    for (const button of buttons) {
      button.disabled = true;
    }
    form.classList.add("is-submitting");
    setBusy(true);

    try {
      const requestUrl = method === "get" ? urlWithFormData(actionUrl, data) : actionUrl;
      const response = await fetchHtml(requestUrl.href, {
        method: method.toUpperCase(),
        body: method === "post" ? data : undefined,
      });
      if (isAttachmentResponse(response) || !isHtmlResponse(response)) {
        form.dataset.ajax = "off";
        form.submit();
        return;
      }
      const html = await response.text();
      const nextUrl =
        method === "get" || response.redirected
          ? response.url || requestUrl.href
          : window.location.href;
      swapShell(html, nextUrl, { push: method === "get" });
    } catch (error) {
      if (error.name !== "AbortError") {
        showInlineMessage("The request could not be completed. Please try again.");
      }
      for (const button of buttons) {
        button.disabled = false;
      }
      form.classList.remove("is-submitting");
    } finally {
      setBusy(false);
    }
  }

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    textArea.style.left = "-9999px";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    document.execCommand("copy");
    textArea.remove();
  }

  function storageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (error) {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      // If storage is unavailable, the current button press still dismisses the notice.
    }
  }

  function setupCookieNotice() {
    const banner = document.getElementById("cookie-banner");
    if (!banner) return;
    const dialog = document.getElementById("cookie-settings-dialog");
    const storageKey = "parafiles-cookie-choice";

    function closeDialog() {
      if (!dialog) return;
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        dialog.hidden = true;
      }
    }

    function rememberChoice(choice) {
      storageSet(storageKey, JSON.stringify({ choice, recorded_at: new Date().toISOString() }));
      banner.hidden = true;
      closeDialog();
    }

    if (storageGet(storageKey)) {
      banner.hidden = true;
    } else {
      banner.hidden = false;
    }

    document.addEventListener("click", (event) => {
      const choiceButton = event.target.closest("[data-cookie-choice]");
      if (choiceButton) {
        event.preventDefault();
        rememberChoice(choiceButton.dataset.cookieChoice);
        return;
      }

      const settingsButton = event.target.closest("[data-cookie-settings]");
      if (settingsButton && dialog) {
        event.preventDefault();
        if (typeof dialog.showModal === "function") {
          dialog.showModal();
        } else {
          dialog.hidden = false;
        }
        return;
      }

      const closeButton = event.target.closest("[data-cookie-settings-close]");
      if (closeButton) {
        event.preventDefault();
        closeDialog();
      }
    });
  }

  document.addEventListener("click", async (event) => {
    const navToggle = event.target.closest(".nav-toggle");
    if (navToggle) {
      event.preventDefault();
      setNavOpen(!document.body.classList.contains("nav-open"));
      return;
    }

    const copyButton = event.target.closest("[data-copy]");
    if (copyButton) {
      event.preventDefault();
      await copyText(copyButton.dataset.copy || "");
      const originalText = copyButton.textContent;
      copyButton.textContent = "Copied";
      setTimeout(() => {
        copyButton.textContent = originalText;
      }, 1200);
      return;
    }

    const link = event.target.closest("a[href]");
    if (!link) return;
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey ||
      (link.target && link.target !== "_self") ||
      link.hasAttribute("download") ||
      link.dataset.ajax === "off"
    ) {
      return;
    }
    const linkUrl = sameOriginUrl(link.href);
    if (linkUrl && revealHashTarget(linkUrl)) {
      event.preventDefault();
      return;
    }
    if (shouldSkipLink(link, event)) return;
    event.preventDefault();
    visit(link.href, { push: true });
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (event.defaultPrevented) return;
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
      return;
    }
    if (shouldSkipForm(form)) return;
    event.preventDefault();
    submitForm(form, event.submitter);
  });

  window.addEventListener("popstate", () => {
    visit(window.location.href, { push: false });
  });

  window.Parafiles = {
    ...(window.Parafiles || {}),
    visit,
  };

  setupCookieNotice();
})();
