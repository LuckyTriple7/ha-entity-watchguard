// Renders the card against DOM stubs and asserts on the produced HTML.
// Run with: node tests/card/smoke.js  (no dependencies, no build step)
//
// Minimal DOM stubs — enough to construct the card and run a full render.
const registry = new Map();
class FakeNode {
  constructor() { this.children = []; this._html = ""; this.dataset = {}; this.style = {}; }
  set innerHTML(v) { this._html = v; }
  get innerHTML() { return this._html; }
  querySelector(sel) { return sel === "ha-card" ? this._card : null; }
  querySelectorAll() { return []; }
  addEventListener() {}
  appendChild(child) { this.children.push(child); return child; }
}
global.HTMLElement = class extends FakeNode {
  attachShadow() { this.shadowRoot = new FakeNode(); return this.shadowRoot; }
  dispatchEvent() {}
};
global.customElements = { define: (name, cls) => registry.set(name, cls) };
global.document = { createElement: (name) => new (registry.get(name) || FakeNode)() };
global.navigator = { language: "en-US" };
global.window = {};
global.Event = class { constructor(type) { this.type = type; } };
global.CustomEvent = global.Event;

require("../../custom_components/entity_watchguard/www/entity-watchguard-card.js");

const since = new Date(Date.now() - 42 * 60000).toISOString();
const hass = {
  language: "de",
  states: {
    "binary_sensor.entity_watchguard_switch": {
      entity_id: "binary_sensor.entity_watchguard_switch",
      state: "on",
      attributes: {
        status: "problem", count: 2, truncated: false,
        details: [
          { entity_id: "switch.pump", name: "Pumpe", since, attempts: 2, given_up: false },
          { entity_id: "switch.shelly", name: "Shelly", since, attempts: 3, given_up: true },
        ],
      },
    },
    "binary_sensor.entity_watchguard_light": {
      entity_id: "binary_sensor.entity_watchguard_light",
      state: "off",
      attributes: { status: "ok", count: 0, details: [] },
    },
    "button.entity_watchguard_check_now": { entity_id: "button.entity_watchguard_check_now", state: "unknown", attributes: {} },
  },
};

const Card = registry.get("entity-watchguard-card");
const card = new Card();
// Shadow root needs a card element for the render path.
card.shadowRoot._card = new FakeNode();
card.shadowRoot.querySelector = (sel) => (sel === "ha-card" ? card.shadowRoot._card : null);

card.setConfig({ type: "custom:entity-watchguard-card" });
card.hass = hass;
const html = card.shadowRoot._card.innerHTML;

const checks = [
  ["German strings from hass.language", html.includes("Jetzt prüfen") && html.includes("nicht verfügbar")],
  ["expandable domain rows", html.includes('data-domain="switch"')],
  ["counter badge", html.includes(">2<")],
  ["plain buttons, no mwc", html.includes('class="action"') && !html.includes("mwc-button")],
  ["no undefined leaked", !html.includes("undefined")],
];

card._toggle("switch");
const expanded = card.shadowRoot._card.innerHTML;
checks.push(["outage details after expand", expanded.includes("switch.pump") && expanded.includes("42 min")]);
checks.push(["gave-up tag", expanded.includes("aufgegeben")]);
checks.push(["attempts shown", expanded.includes("2 Versuche")]);
checks.push(["ignore button inside row", expanded.includes('class="ignore"') && !expanded.includes("ha-icon-button")]);

// Re-setting hass with unchanged data must not rebuild the DOM — doing so on
// every state change in the system used to swallow clicks and flicker :hover.
let rebuilds = 0;
const cardNode = card.shadowRoot._card;
Object.defineProperty(cardNode, "innerHTML", {
  set(value) { rebuilds++; this._html = value; },
  get() { return this._html; },
  configurable: true,
});
card.hass = hass;
card.hass = hass;
checks.push(["unchanged hass does not rebuild the card", rebuilds === 0]);
card._toggle("switch");
checks.push(["expanding still rebuilds", rebuilds === 1]);
card._toggle("switch");

card.setConfig({ type: "custom:entity-watchguard-card", language: "en" });
card.hass = hass;
checks.push(["forced language:en overrides hass", card.shadowRoot._card.innerHTML.includes("Check now")]);

const Editor = registry.get("entity-watchguard-card-editor");
const editor = new Editor();
editor.hass = hass;
editor.setConfig({ type: "custom:entity-watchguard-card" });
checks.push(["editor renders with language picker", editor.innerHTML.includes('id="language"')]);
checks.push(["editor has no internal elements", !/ha-textfield|ha-switch|ha-formfield/.test(editor.innerHTML)]);

let failed = 0;
for (const [name, ok] of checks) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failed++;
}
process.exit(failed ? 1 : 0);
