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
global.customElements = {
  define: (name, cls) => {
    if (registry.has(name)) throw new Error(`"${name}" has already been defined`);
    registry.set(name, cls);
  },
  get: (name) => registry.get(name),
};
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

// --- renamed entities, resolved through the registry ---------------------
// Everything below is renamed away from the "entity_watchguard" id shape the
// card used to match on: only hass.entities (platform, translation_key) and
// the sensors' own `domain` attribute identify them now.
const renamedHass = {
  language: "en",
  states: {
    "binary_sensor.my_switches": {
      entity_id: "binary_sensor.my_switches",
      state: "on",
      attributes: {
        domain: "switch", status: "problem", count: 2, truncated: false,
        details: [
          { entity_id: "switch.pump", name: "Pumpe", since, attempts: 2, given_up: false },
          { entity_id: "switch.shelly", name: "Shelly", since, attempts: 3, given_up: true },
        ],
      },
    },
    "binary_sensor.house_overall": {
      entity_id: "binary_sensor.house_overall",
      state: "off",
      // The aggregate sensor has no `domain` and must not show up as a row.
      attributes: { status: "ok", count: 0, details: [] },
    },
    "button.look_again": { entity_id: "button.look_again", state: "unknown", attributes: {} },
    "button.fix_it": { entity_id: "button.fix_it", state: "unknown", attributes: {} },
    "binary_sensor.other_integration": {
      entity_id: "binary_sensor.other_integration",
      state: "on",
      attributes: { domain: "switch", status: "problem", count: 9, details: [] },
    },
  },
  entities: {
    "binary_sensor.my_switches": { entity_id: "binary_sensor.my_switches", platform: "entity_watchguard" },
    "binary_sensor.house_overall": { entity_id: "binary_sensor.house_overall", platform: "entity_watchguard", translation_key: "problem" },
    "button.look_again": { entity_id: "button.look_again", platform: "entity_watchguard", translation_key: "check_now" },
    "button.fix_it": { entity_id: "button.fix_it", platform: "entity_watchguard", translation_key: "recover_now" },
    "binary_sensor.other_integration": { entity_id: "binary_sensor.other_integration", platform: "some_other_integration" },
  },
};

const renamed = new Card();
renamed.shadowRoot._card = new FakeNode();
renamed.shadowRoot.querySelector = (sel) => (sel === "ha-card" ? renamed.shadowRoot._card : null);
renamed.setConfig({ type: "custom:entity-watchguard-card" });
renamed.hass = renamedHass;
const renamedHtml = renamed.shadowRoot._card.innerHTML;

const rows = renamed._sensors();
checks.push(["renamed ids still resolve to one domain row", rows.length === 1 && rows[0].domain === "switch"]);
checks.push(["aggregate sensor is not listed as a row", !rows.some((r) => r.entityId === "binary_sensor.house_overall")]);
checks.push(["another integration's sensor is ignored", !rows.some((r) => r.entityId === "binary_sensor.other_integration")]);
checks.push(["renamed check button found by translation_key", renamed._button("check_now") === "button.look_again"]);
checks.push(["renamed recover button found by translation_key", renamed._button("recover_now") === "button.fix_it"]);
checks.push(["renamed card renders the domain", renamedHtml.includes('data-domain="switch"')]);

// Loading a second copy must not throw (the retired standalone card may
// still be listed as a resource next to the bundled one).
const cardPath = require.resolve("../../custom_components/entity_watchguard/www/entity-watchguard-card.js");
delete require.cache[cardPath];
let secondLoadOk = true;
try { require(cardPath); } catch (err) { secondLoadOk = false; }
checks.push(["loading the card twice does not throw", secondLoadOk]);
checks.push(["card is listed in the card picker once", window.customCards.filter((c) => c.type === "entity-watchguard-card").length === 1]);

// The resource URL carries the manifest version as ?v=; the banner should match it.
const fs = require("fs");
const path = require("path");
const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, "../../custom_components/entity_watchguard/manifest.json"), "utf8"));
const cardSource = fs.readFileSync(cardPath, "utf8");
checks.push(["CARD_VERSION matches manifest.json", cardSource.includes(`const CARD_VERSION = "${manifest.version}";`)]);

let failed = 0;
for (const [name, ok] of checks) {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failed++;
}
process.exit(failed ? 1 : 0);
