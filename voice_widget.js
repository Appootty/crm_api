/* Voice assistant for the management portal.
   Click the microphone once to start a conversation: speak, pause, and the question is sent automatically;
   the answer is shown (and read aloud if switched on), then it listens again. Click the button to end. */
(function () {
  "use strict";
  var CFG = window.VOICE_CFG || {};
  var SILENCE_MS = CFG.silenceMs || 1300;     // pause that ends a question
  var IDLE_MS = CFG.idleMs || 45000;          // no speech for this long ends the conversation
  var MAX_UTTER_MS = CFG.maxUtterMs || 30000; // longest single question
  var MIN_THRESHOLD = 0.025;

  function newSid() { try { return crypto.randomUUID(); } catch (e) { return String(Date.now()) + Math.random(); } }
  var sid = newSid();
  var speakOn = true;
  try { speakOn = localStorage.getItem("voice_speak") !== "0"; } catch (e) {}

  var css = document.createElement("style");
  css.textContent =
    "#vx{position:fixed;left:236px;bottom:20px;z-index:50;font:14px/1.45 'Segoe UI',system-ui,sans-serif;color:#1d2340}" +
    "#vx.fl{left:auto;right:20px}#vx *{box-sizing:border-box}" +
    "#vxp{display:none;width:min(400px,calc(100vw - 260px));max-height:70vh;overflow:auto;background:#fff;border-radius:14px;padding:14px 16px;box-shadow:0 8px 30px rgba(30,40,100,.25)}" +
    "#vxp.on{display:block}" +
    "#vxp h4{margin:0 0 8px;font-size:14px;display:flex;justify-content:space-between;align-items:center;gap:8px}" +
    "#vxp label{font-size:12px;font-weight:400;color:#6b7394;display:flex;gap:4px;align-items:center;cursor:pointer}" +
    "#vxp .t{margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #eef0f8}" +
    "#vxp .q{color:#6b7394;font-size:13px;margin-bottom:4px}#vxp .a{font-size:14px;white-space:pre-wrap}" +
    "#vxp .e{color:#c2264f}#vxp .h{color:#6b7394;font-size:12px}#vxp .s{font-size:13px;font-weight:600}" +
    "#vxp .s.live{color:#ef4f7b}#vxp .s.work{color:#6b7394}#vxp .s.talk{color:#12b8a6}" +
    "#vxp table{width:100%;border-collapse:collapse;font-size:12px;margin-top:6px}" +
    "#vxp th{text-align:left;color:#6b7394;border-bottom:2px solid #e6e9f4;padding:4px 6px}#vxp td{border-bottom:1px solid #e6e9f4;padding:4px 6px}" +
    "#vxb.nav{display:flex;align-items:center;gap:10px;width:100%;margin-top:3px;padding:10px 12px;border:0;border-radius:9px;background:none;color:#c9cfee;font:inherit;font-size:14px;text-align:left;cursor:pointer}" +
    "#vxb.nav:hover{background:rgba(255,255,255,.08);color:#fff}#vxb.nav .ic{width:46px;height:46px;flex-shrink:0;display:block}#vxb .av{width:100%;height:100%;display:block;overflow:visible}" +
    "#vxb.nav small{display:block;font-size:11px;opacity:.85}" +
    "#vxb.nav.rec,#vxb.nav.hear{background:rgba(239,79,123,.3);color:#fff}" +
    "#vxb.nav.busy{background:rgba(255,255,255,.14);color:#fff}#vxb.nav.talk{background:rgba(18,184,166,.32);color:#fff}" +
    "#vxb.nav:disabled{opacity:.45;cursor:not-allowed}" +
    "#vxb .ring{fill:none;stroke:#ef4f7b;stroke-width:2;opacity:0;transform-box:fill-box;transform-origin:center}" +
    "#vxb.rec .ring,#vxb.hear .ring{animation:vxring 1.6s infinite}#vxb.hear .ring{stroke:#ff3d71;animation-duration:.7s}" +
    "#vxb.talk .ring{stroke:#12b8a6;animation:vxring 1.1s infinite}" +
    "#vxb .mouth{opacity:0;transform-box:fill-box;transform-origin:center}#vxb.talk .mouth{opacity:1;animation:vxmouth .32s infinite alternate}#vxb.talk .smile{opacity:0}" +
    "#vxb .dots{opacity:0}#vxb.busy .dots{opacity:1}#vxb.busy .dots circle{animation:vxdot 1s infinite}#vxb.busy .dots circle:nth-child(2){animation-delay:.2s}#vxb.busy .dots circle:nth-child(3){animation-delay:.4s}" +
    "#vxb.talk image{transform-box:fill-box;transform-origin:center;animation:vxbreath .9s infinite alternate}@keyframes vxbreath{to{transform:scale(1.04)}}" +
    "@keyframes vxring{0%{opacity:.9;transform:scale(.9)}100%{opacity:0;transform:scale(1.3)}}@keyframes vxmouth{from{transform:scaleY(.6)}to{transform:scaleY(3.4)}}@keyframes vxdot{0%,100%{opacity:.25}50%{opacity:1}}" +
    "#vxp .hd{display:flex;align-items:center;gap:8px}#vxp .hd .av{width:34px;height:34px}" +
    "@media(max-width:860px){#vx{left:12px;right:12px;bottom:12px}#vxp{width:100%}#vxb.nav{width:auto;margin:2px}}" +
    "#vxb.fl{display:block;width:64px;height:64px;padding:0;border-radius:50%;border:0;cursor:pointer;margin-top:12px;margin-left:auto;background:none;box-shadow:0 6px 18px rgba(79,109,245,.5)}" +
    "#vxb.fl:disabled{opacity:.45;cursor:not-allowed}";
  document.head.appendChild(css);

  // Drawn portrait (original artwork). If a file voice_avatar.png/jpg/webp exists next to portal.py, that photo is used instead.
  var AV_DRAWN = "<svg class=\"av\" viewBox=\"0 0 100 100\"> <defs> <linearGradient id=\"vxbg\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\"><stop offset=\"0\" stop-color=\"#6f86ff\"/><stop offset=\"1\" stop-color=\"#8f6bf0\"/></linearGradient> <clipPath id=\"vxc\"><circle cx=\"50\" cy=\"50\" r=\"47\"/></clipPath> <linearGradient id=\"vxskin\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"0.3\"><stop offset=\"0\" stop-color=\"#f6d8c0\"/><stop offset=\".55\" stop-color=\"#eec4a4\"/><stop offset=\"1\" stop-color=\"#dfa882\"/></linearGradient> <linearGradient id=\"vxneck\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\"><stop offset=\"0\" stop-color=\"#c98f6c\"/><stop offset=\"1\" stop-color=\"#e3b08d\"/></linearGradient> <linearGradient id=\"vxhair\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\"><stop offset=\"0\" stop-color=\"#5b3a28\"/><stop offset=\"1\" stop-color=\"#26160f\"/></linearGradient> <linearGradient id=\"vxblz\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\"><stop offset=\"0\" stop-color=\"#2c3556\"/><stop offset=\"1\" stop-color=\"#171c33\"/></linearGradient> <linearGradient id=\"vxmet\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\"><stop offset=\"0\" stop-color=\"#5b6275\"/><stop offset=\"1\" stop-color=\"#1e2230\"/></linearGradient> <radialGradient id=\"vxblush\"><stop offset=\"0\" stop-color=\"#e57f78\" stop-opacity=\".38\"/><stop offset=\"1\" stop-color=\"#e57f78\" stop-opacity=\"0\"/></radialGradient> <radialGradient id=\"vxbokeh\"><stop offset=\"0\" stop-color=\"#fff\" stop-opacity=\".35\"/><stop offset=\"1\" stop-color=\"#fff\" stop-opacity=\"0\"/></radialGradient> </defs> <circle class=\"ring\" cx=\"50\" cy=\"50\" r=\"48.5\"/> <circle cx=\"50\" cy=\"50\" r=\"47\" fill=\"url(#vxbg)\"/> <g clip-path=\"url(#vxc)\"> <circle cx=\"22\" cy=\"24\" r=\"12\" fill=\"url(#vxbokeh)\"/><circle cx=\"82\" cy=\"34\" r=\"9\" fill=\"url(#vxbokeh)\"/><circle cx=\"76\" cy=\"14\" r=\"6\" fill=\"url(#vxbokeh)\"/> <g transform=\"translate(50 52) scale(1.2) translate(-50 -50)\"> <path d=\"M31 46 C25 26 37 15 50 15 C63 15 75 26 69 46 C71 60 69 74 74 90 L26 90 C31 74 29 60 31 46 Z\" fill=\"url(#vxhair)\"/> <path d=\"M14 104 C14 86 28 79 43 76 L57 76 C72 79 86 86 86 104 Z\" fill=\"url(#vxblz)\"/> <path d=\"M44 58 L44 79 Q50 84 56 79 L56 58 Z\" fill=\"url(#vxneck)\"/> <path d=\"M43 76 L50 90 L57 76 Q50 82 43 76 Z\" fill=\"#f6f7fb\"/> <path d=\"M43 76 L33 98 L46 87 Z\" fill=\"#232a47\"/><path d=\"M57 76 L67 98 L54 87 Z\" fill=\"#232a47\"/> <path d=\"M43 76 L36 92\" stroke=\"#3a4468\" stroke-width=\".7\" fill=\"none\"/><path d=\"M57 76 L64 92\" stroke=\"#3a4468\" stroke-width=\".7\" fill=\"none\"/> <path d=\"M35 44 C35 31 42 24 50 24 C58 24 65 31 65 44 C65 56 59 68 50 69 C41 68 35 56 35 44 Z\" fill=\"url(#vxskin)\"/> <ellipse cx=\"41\" cy=\"54\" rx=\"6\" ry=\"4.2\" fill=\"url(#vxblush)\"/><ellipse cx=\"59\" cy=\"54\" rx=\"6\" ry=\"4.2\" fill=\"url(#vxblush)\"/> <path d=\"M39 63 C43 68 57 68 61 63 C58 70 42 70 39 63 Z\" fill=\"#c98f6c\" opacity=\".25\"/> <path d=\"M34.5 45 C32.5 29 40 20 51 20 C62.5 20 68 30 65.5 45 C64.5 37 61 32.5 53.5 31.5 C45 30.5 38 34 34.5 45 Z\" fill=\"url(#vxhair)\"/> <path d=\"M40 25 C44 22 50 21.5 55 22.5\" stroke=\"#9a6a48\" stroke-width=\"1\" fill=\"none\" stroke-linecap=\"round\" opacity=\".55\"/> <path d=\"M37 31 C40 27 45 25.5 50 25.5\" stroke=\"#8a5c3d\" stroke-width=\".7\" fill=\"none\" stroke-linecap=\"round\" opacity=\".45\"/> <path d=\"M38.3 40.4 Q43.2 37.4 48.2 39.8\" stroke=\"#3b271b\" stroke-width=\"1.35\" fill=\"none\" stroke-linecap=\"round\"/> <path d=\"M51.8 39.8 Q56.8 37.4 61.7 40.4\" stroke=\"#3b271b\" stroke-width=\"1.35\" fill=\"none\" stroke-linecap=\"round\"/> <path d=\"M39.4 44.7 Q43.5 41.7 47.6 44.7 Q43.5 47.2 39.4 44.7 Z\" fill=\"#fbf7f3\"/> <path d=\"M52.4 44.7 Q56.5 41.7 60.6 44.7 Q56.5 47.2 52.4 44.7 Z\" fill=\"#fbf7f3\"/> <circle cx=\"43.5\" cy=\"44.5\" r=\"2.15\" fill=\"#6b4328\"/><circle cx=\"56.5\" cy=\"44.5\" r=\"2.15\" fill=\"#6b4328\"/> <circle cx=\"43.5\" cy=\"44.5\" r=\"1\" fill=\"#1b100b\"/><circle cx=\"56.5\" cy=\"44.5\" r=\"1\" fill=\"#1b100b\"/> <circle cx=\"44.3\" cy=\"43.7\" r=\".55\" fill=\"#fff\"/><circle cx=\"57.3\" cy=\"43.7\" r=\".55\" fill=\"#fff\"/> <path d=\"M38.9 44.9 Q43.5 41 48.1 44.9\" stroke=\"#24150e\" stroke-width=\"1.1\" fill=\"none\" stroke-linecap=\"round\"/> <path d=\"M51.9 44.9 Q56.5 41 61.1 44.9\" stroke=\"#24150e\" stroke-width=\"1.1\" fill=\"none\" stroke-linecap=\"round\"/> <path d=\"M40.5 46.6 Q43.5 48 46.5 46.6\" stroke=\"#b98062\" stroke-width=\".5\" fill=\"none\" opacity=\".6\"/> <path d=\"M53.5 46.6 Q56.5 48 59.5 46.6\" stroke=\"#b98062\" stroke-width=\".5\" fill=\"none\" opacity=\".6\"/> <path d=\"M50 46.5 Q48.6 52.5 47.4 55.4 Q50 57 52.6 55.4 Q51.4 52.5 50 46.5\" stroke=\"#c48a68\" stroke-width=\".8\" fill=\"none\" opacity=\".75\" stroke-linecap=\"round\"/> <ellipse cx=\"48.4\" cy=\"55.6\" rx=\".7\" ry=\".45\" fill=\"#9c6048\" opacity=\".7\"/><ellipse cx=\"51.6\" cy=\"55.6\" rx=\".7\" ry=\".45\" fill=\"#9c6048\" opacity=\".7\"/> <g class=\"smile\"> <path d=\"M43.6 60.4 Q47 58.4 50 59.4 Q53 58.4 56.4 60.4 Q50 66.4 43.6 60.4 Z\" fill=\"#c4625a\"/> <path d=\"M43.6 60.4 Q50 63 56.4 60.4\" stroke=\"#8c3b38\" stroke-width=\".55\" fill=\"none\"/> <path d=\"M46.5 62.9 Q50 64.6 53.5 62.9\" stroke=\"#e9948a\" stroke-width=\".6\" fill=\"none\" stroke-linecap=\"round\" opacity=\".8\"/> </g> <g class=\"mouth\"><ellipse cx=\"50\" cy=\"61.7\" rx=\"3.6\" ry=\"1.6\" fill=\"#6e2b2f\"/><path d=\"M46.6 60.9 Q50 59.9 53.4 60.9 L53.1 61.7 Q50 61 46.9 61.7 Z\" fill=\"#fbf7f3\"/><path d=\"M45.6 60.4 Q50 58.6 54.4 60.4\" stroke=\"#c4625a\" stroke-width=\"1.2\" fill=\"none\"/></g> <path d=\"M33.6 45 C31.6 14 68.4 14 66.4 45\" stroke=\"url(#vxmet)\" stroke-width=\"2.6\" fill=\"none\" stroke-linecap=\"round\"/> <rect x=\"29.6\" y=\"40\" width=\"6.2\" height=\"12.5\" rx=\"3\" fill=\"url(#vxmet)\"/><rect x=\"64.2\" y=\"40\" width=\"6.2\" height=\"12.5\" rx=\"3\" fill=\"url(#vxmet)\"/> <rect x=\"30.9\" y=\"42\" width=\"2.2\" height=\"8.5\" rx=\"1.1\" fill=\"#fff\" opacity=\".18\"/><rect x=\"65.5\" y=\"42\" width=\"2.2\" height=\"8.5\" rx=\"1.1\" fill=\"#fff\" opacity=\".12\"/> <path d=\"M32.8 51.5 C33 63 39.5 67.5 46 65.2\" stroke=\"#1e2230\" stroke-width=\"1.5\" fill=\"none\" stroke-linecap=\"round\"/> <ellipse cx=\"46.8\" cy=\"65.1\" rx=\"2.7\" ry=\"1.7\" fill=\"#14171f\" transform=\"rotate(-16 46.8 65.1)\"/><ellipse cx=\"46.1\" cy=\"64.5\" rx=\"1.1\" ry=\".6\" fill=\"#fff\" opacity=\".35\"/> </g> </g> <g class=\"dots\" fill=\"#fff\"><circle cx=\"80\" cy=\"13\" r=\"2.5\"/><circle cx=\"87\" cy=\"13\" r=\"2.5\"/><circle cx=\"94\" cy=\"13\" r=\"2.5\"/></g> </svg>";
  var AV_PHOTO = "<svg class=\"av\" viewBox=\"0 0 100 100\"><defs><clipPath id=\"vxpc\"><circle cx=\"50\" cy=\"50\" r=\"47\"/></clipPath></defs><circle class=\"ring\" cx=\"50\" cy=\"50\" r=\"48.5\"/><image href=\"/voice-avatar\" x=\"3\" y=\"3\" width=\"94\" height=\"94\" preserveAspectRatio=\"xMidYMid slice\" clip-path=\"url(#vxpc)\"/><g class=\"dots\" fill=\"#fff\"><circle cx=\"80\" cy=\"13\" r=\"2.5\"/><circle cx=\"87\" cy=\"13\" r=\"2.5\"/><circle cx=\"94\" cy=\"13\" r=\"2.5\"/></g></svg>";
  var AV = AV_DRAWN;

  var root = document.createElement("div"); root.id = "vx";
  var panel = document.createElement("div"); panel.id = "vxp";
  var btn = document.createElement("button"); btn.id = "vxb"; btn.type = "button";
  root.appendChild(panel); document.body.appendChild(root);
  // Put the button in the side menu, under the last menu item. If the page has no side menu, float it bottom right.
  var menu = document.getElementById("menu"), floating = !(menu && menu.parentNode);
  if (floating) { root.classList.add("fl"); root.appendChild(btn); } else { menu.parentNode.insertBefore(btn, menu.nextSibling); }

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  // ---------------------------------------------------------------- state
  var enabled = false, active = false, phase = "idle"; // idle | listening | hearing | thinking | speaking
  var stream = null, actx = null, analyser = null, buf = null, timer = null, rec = null;
  var ambient = 0.01, threshold = MIN_THRESHOLD, voicedMs = 0, lastVoice = 0, utterStart = 0, listenStart = 0, recStart = 0;
  var turns = [], statusText = "", statusCls = "", errors = 0, ttsTimer = null;

  function label() {
    var st = active ? ({ listening: "rec", hearing: "hear", thinking: "busy", speaking: "talk" }[phase] || "rec") : "";
    btn.className = (floating ? "fl" : "nav") + (st ? " " + st : "");
    var main = active ? "End conversation" : "Talk to assistant";
    var sub = active ? ({ listening: "Listening...", hearing: "Hearing you...", thinking: "Thinking...", speaking: "Speaking..." }[phase] || "") : "";
    btn.textContent = "";
    var ic = el("span", "ic"); ic.innerHTML = AV; btn.appendChild(ic);
    if (!floating) { var t = el("span", null, main); if (sub) t.appendChild(el("small", null, sub)); btn.appendChild(t); }
    btn.title = !enabled ? "Voice assistant is not switched on yet" : (active ? "Click to end the conversation" : "Click to start talking");
    btn.setAttribute("aria-label", main);
  }

  function render() {
    panel.textContent = "";
    var h = el("h4"), hd = el("span", "hd"); hd.innerHTML = AV; hd.appendChild(el("span", null, "Voice assistant")); h.appendChild(hd);
    var lab = el("label"), cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = speakOn;
    cb.onchange = function () {
      speakOn = cb.checked; try { localStorage.setItem("voice_speak", speakOn ? "1" : "0"); } catch (e) {}
      if (!speakOn && window.speechSynthesis) speechSynthesis.cancel();
    };
    lab.appendChild(cb); lab.appendChild(document.createTextNode("Read aloud")); h.appendChild(lab); panel.appendChild(h);
    turns.forEach(function (t) {
      var d = el("div", "t");
      if (t.q) d.appendChild(el("div", "q", "You: " + t.q));
      d.appendChild(el("div", t.err ? "a e" : "a", t.a));
      if (t.table) d.appendChild(tableEl(t.table));
      panel.appendChild(d);
    });
    if (statusText) panel.appendChild(el("div", "s " + statusCls, statusText));
    panel.classList.add("on"); panel.scrollTop = panel.scrollHeight;
  }

  function tableEl(t) {
    var tb = el("table"), hr = el("tr");
    t.columns.forEach(function (c) { hr.appendChild(el("th", null, c)); }); tb.appendChild(hr);
    t.rows.forEach(function (r) { var tr = el("tr"); r.forEach(function (v) { tr.appendChild(el("td", null, v)); }); tb.appendChild(tr); });
    return tb;
  }

  function setPhase(p, text, cls) { phase = p; statusText = text || ""; statusCls = cls || ""; label(); render(); }

  // ---------------------------------------------------------------- setup
  fetch("/voice/status", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (s) {
    enabled = !!s.enabled; btn.disabled = !enabled; label();
    if (s.avatar) { var im = new Image(); im.onload = function () { AV = AV_PHOTO; label(); if (panel.classList.contains("on")) render(); }; im.src = "/voice-avatar"; }
  }).catch(function () { btn.disabled = true; });
  label();

  function pickMime() {
    var c = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
    for (var i = 0; i < c.length; i++) { if (window.MediaRecorder && MediaRecorder.isTypeSupported(c[i])) return c[i]; }
    return "";
  }
  var mime = "";

  async function startConversation() {
    if (!enabled || active) return;
    if (!navigator.mediaDevices || !window.MediaRecorder || !(window.AudioContext || window.webkitAudioContext)) {
      turns = [{ a: "This browser cannot record audio. Use a current Chrome, Edge, Safari or Firefox over HTTPS.", err: true }]; statusText = ""; render(); return;
    }
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
    catch (e) { turns = [{ a: "Microphone blocked. Allow the microphone for this site in the browser, then click again.", err: true }]; statusText = ""; render(); return; }
    actx = new (window.AudioContext || window.webkitAudioContext)();
    if (actx.resume) { try { await actx.resume(); } catch (e) {} }
    analyser = actx.createAnalyser(); analyser.fftSize = 1024; buf = new Uint8Array(analyser.fftSize);
    actx.createMediaStreamSource(stream).connect(analyser);
    mime = pickMime(); sid = newSid(); turns = []; errors = 0; ambient = 0.01; threshold = MIN_THRESHOLD;
    active = true;
    timer = setInterval(tick, 50);
    beginListening();
  }

  function endConversation(reason) {
    if (!active) return;
    active = false;
    clearInterval(timer); timer = null; clearTimeout(ttsTimer);
    if (window.speechSynthesis) speechSynthesis.cancel();
    discardRecorder();
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); }); stream = null;
    if (actx) { try { actx.close(); } catch (e) {} } actx = null; analyser = null;
    phase = "idle"; statusText = reason || "Conversation ended. Click the microphone to start again."; statusCls = "";
    label(); render();
  }

  // ---------------------------------------------------------------- listening loop
  function level() {
    analyser.getByteTimeDomainData(buf);
    var s = 0; for (var i = 0; i < buf.length; i++) { var v = (buf[i] - 128) / 128; s += v * v; }
    return Math.sqrt(s / buf.length);
  }

  function startRecorder() {
    var r = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    r.chunks = []; r.keep = false;
    r.ondataavailable = function (e) { if (e.data && e.data.size) r.chunks.push(e.data); };
    r.onstop = function () { if (r.keep) send(new Blob(r.chunks, { type: (r.mimeType || mime || "audio/webm").split(";")[0] })); };
    r.start(); rec = r; recStart = Date.now();
  }
  function discardRecorder() { if (rec) { rec.keep = false; try { if (rec.state === "recording") rec.stop(); } catch (e) {} rec = null; } }

  function beginListening() {
    voicedMs = 0; listenStart = Date.now();
    startRecorder();
    setPhase("listening", "Listening... just speak. Click End conversation when you are done.", "live");
  }

  function tick() {
    if (!active || !analyser) return;
    var now = Date.now();
    if (phase === "listening" || phase === "hearing") {
      var lv = level();
      var loud = lv > threshold;
      if (phase === "listening") {
        if (loud) voicedMs += 50; else { voicedMs = 0; ambient = ambient * 0.95 + lv * 0.05; threshold = Math.max(MIN_THRESHOLD, ambient * 3 + 0.01); }
        if (voicedMs >= 200) { phase = "hearing"; lastVoice = now; utterStart = now - voicedMs; statusText = "Hearing you..."; statusCls = "live"; label(); render(); return; }
        if (now - listenStart > IDLE_MS) { endConversation("Conversation ended because nothing was said. Click the microphone to start again."); return; }
        if (now - recStart > 3000) { discardRecorder(); startRecorder(); } // keep silence out of the recording
      } else {
        if (loud) lastVoice = now;
        if (now - lastVoice > SILENCE_MS || now - utterStart > MAX_UTTER_MS) finishUtterance();
      }
    }
  }

  function finishUtterance() {
    setPhase("thinking", "Thinking...", "work");
    if (rec) { rec.keep = true; var r = rec; rec = null; try { r.stop(); } catch (e) {} }
  }

  // ---------------------------------------------------------------- ask and answer
  async function send(blob) {
    if (!active) return;
    if (blob.size < 800) { beginListening(); return; }
    var type = blob.type || "audio/webm";
    try {
      var r = await fetch("/voice/ask", { method: "POST", credentials: "same-origin", body: blob, headers: { "Content-Type": type, "X-Session": sid } });
      if (r.status === 401) { location.href = "/login?next=/portal"; return; }
      var d = await r.json().catch(function () { return {}; });
      if (!r.ok) throw new Error(d.detail || ("Error " + r.status));
      errors = 0;
      turns.push({ q: d.transcript, a: d.answer || "No answer.", table: d.table });
      if (turns.length > 10) turns.shift();
      if (!active) return;
      answerThenListen(d.answer);
    } catch (e) {
      if (!active) return;
      errors++; turns.push({ a: String(e.message || e), err: true });
      if (errors >= 3) { endConversation("Conversation ended after repeated errors."); return; }
      beginListening();
    }
  }

  function answerThenListen(text) {
    if (!(speakOn && text && window.speechSynthesis)) { beginListening(); return; }
    var done = false;
    function next() { if (done) return; done = true; clearTimeout(ttsTimer); if (active) beginListening(); }
    setPhase("speaking", "Speaking... click End conversation to stop.", "talk");
    var u = new SpeechSynthesisUtterance(text);
    u.onend = next; u.onerror = next;
    ttsTimer = setTimeout(next, Math.max(4000, text.length * 110)); // in case the browser never reports the end
    speechSynthesis.cancel(); speechSynthesis.speak(u);
  }

  btn.addEventListener("click", function () { if (active) endConversation(); else startConversation(); });
  window.addEventListener("pagehide", function () { endConversation(); });
})();
