"use strict";
// Touchscreen kiosk mode, enabled with ?kiosk=1 (the kiosk service opens
// the UI that way). Adds big touch targets, an always-visible E-stop bar
// and an on-screen keyboard, since the kiosk has no physical keyboard.

(function () {
  if (!/[?&]kiosk=1\b/.test(location.search)) return;
  document.documentElement.classList.add("kiosk");
  // Landscape panels (800x480 to 1280x800): size the live chart to fit beside the controls.
  if (window.innerHeight <= 800 && window.innerWidth >= 700) {
    const wide = window.innerWidth >= 1150;  // chart runs the full height beside readout + camera
    $("chart").setAttribute("height", String(wide ? window.innerHeight - 290
      : Math.min(380, Math.max(160, window.innerHeight - 305))));
  }

  // ---- always-visible E-stop -------------------------------------------
  const bar = document.createElement("div");
  bar.className = "kiosk-bar";
  bar.innerHTML = '<button class="btn estop" type="button">EMERGENCY STOP</button>';
  bar.firstChild.onclick = () => act(() => api("/api/firing/estop", { method: "POST" }));
  document.body.appendChild(bar);

  // ---- on-screen keyboard -----------------------------------------------
  const LAYOUTS = {
    num: [["7", "8", "9"], ["4", "5", "6"], ["1", "2", "3"], ["-", "0", "."], ["⌫", "Done"]],
    text: [
      ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
      ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
      ["a", "s", "d", "f", "g", "h", "j", "k", "l", "-"],
      ["⇧", "z", "x", "c", "v", "b", "n", "m", ".", "⌫"],
      ["@", "/", ":", "space", "(", ")", "Done"],
    ],
  };
  const kb = document.createElement("div");
  kb.className = "osk";
  kb.hidden = true;
  document.body.appendChild(kb);
  let target = null, shift = false, layout = null;
  let buf = "", orig = "";   // number pad edits a buffer: "12." isn't a valid <input type=number> value

  function render(name) {
    layout = name;
    kb.className = "osk osk-" + name;
    kb.innerHTML = "";
    if (name === "num") {
      const d = document.createElement("div");
      d.className = "osk-display";
      d.textContent = buf || orig || "0";
      d.classList.toggle("placeholder", !buf);
      kb.appendChild(d);
    }
    for (const row of LAYOUTS[name]) {
      const r = document.createElement("div");
      r.className = "osk-row";
      for (const k of row) {
        const b = document.createElement("button");
        b.type = "button";
        b.dataset.k = k;
        b.textContent = k === "space" ? "space" : shift && k.length === 1 ? k.toUpperCase() : k;
        if (k.length > 1) b.className = "osk-wide";
        r.appendChild(b);
      }
      kb.appendChild(r);
    }
  }

  // pointerdown + preventDefault keeps focus (and the caret) in the input.
  kb.addEventListener("pointerdown", (e) => {
    const b = e.target.closest("button");
    e.preventDefault();
    e.stopPropagation(); // keys are re-rendered, so the outside-tap check below would misfire
    if (!b || !target) return;
    const k = b.dataset.k;
    if (k === "Done") return close();
    if (k === "⇧") { shift = !shift; return render(layout); }
    if (layout === "num") {
      if (k === "⌫") buf = buf.slice(0, -1);
      else if (k === "-") buf = buf.startsWith("-") ? buf.slice(1) : "-" + buf;
      else if (!(k === "." && buf.includes("."))) buf += k;
      const n = parseFloat(buf);
      target.value = isNaN(n) ? "" : String(n);
      target.dispatchEvent(new Event("input", { bubbles: true }));
      return render("num");
    }
    let v = target.value;
    if (k === "⌫") v = v.slice(0, -1);
    else v += k === "space" ? " " : shift ? k.toUpperCase() : k;
    target.value = v;
    target.dispatchEvent(new Event("input", { bubbles: true }));
    if (shift && k.length === 1) { shift = false; render(layout); }
  });

  function open(el) {
    target = el;
    buf = "";
    orig = el.value;
    render(el.type === "number" ? "num" : "text");
    kb.hidden = false;
    document.body.classList.add("osk-open");
    // Text keyboard is tall: put the field at the top of the screen, above it.
    el.scrollIntoView({ block: layout === "text" ? "start" : "center", behavior: "smooth" });
  }
  function close() {
    kb.hidden = true;
    document.body.classList.remove("osk-open");
    if (target && layout === "num" && buf === "") {
      target.value = orig;
      target.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (target) { target.dispatchEvent(new Event("change", { bubbles: true })); target.blur(); }
    target = null;
  }

  document.addEventListener("focusin", (e) => {
    const el = e.target;
    if (el.matches("input:not([type=checkbox]):not([type=file]), textarea")) {
      el.setAttribute("inputmode", "none");
      open(el);
    }
  });
  document.addEventListener("pointerdown", (e) => {
    if (!kb.hidden && !kb.contains(e.target) && e.target !== target) close();
  });
})();
