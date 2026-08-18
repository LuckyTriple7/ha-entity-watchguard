/**
 * Entity Watchguard dashboard card.
 *
 * Reads the per-domain problem sensors this integration creates and renders
 * them as collapsible rows. No build step on purpose — plain custom elements,
 * shipped straight out of the integration's www/ folder.
 */

// The custom element tag — note the dashes. The integration domain
// (entity_watchguard) is not a valid custom element name.
const CARD_TAG = "entity-watchguard-card";

const STRINGS = {
  de: {
      title: "Entity Watchguard",
      offline: "nicht verfügbar",
      allOk: "Alles verfügbar",
      warming: "Startphase läuft …",
      check: "Jetzt prüfen",
      recover: "Wiederherstellen",
      since: "seit",
      attempts: "Versuche",
      gaveUp: "aufgegeben",
      ignore: (label) => `Ignorieren (Label „${label}“)`,
      ignored: "Label gesetzt",
      checked: "Geprüft",
      recovering: "Wiederherstellung gestartet – Neuprüfung folgt",
      failed: "Fehlgeschlagen",
      noSensors: "Keine Entity-Watchguard-Sensoren gefunden.",
      more: (n) => `… und ${n} weitere`,
    },
  en: {
      title: "Entity Watchguard",
      offline: "unavailable",
      allOk: "All available",
      warming: "Warming up …",
      check: "Check now",
      recover: "Recover now",
      since: "since",
      attempts: "attempts",
      gaveUp: "gave up",
      ignore: (label) => `Ignore (label “${label}”)`,
      ignored: "Label applied",
      checked: "Checked",
      recovering: "Recovery started – re-check follows",
      failed: "Failed",
      noSensors: "No Entity Watchguard sensors found.",
      more: (n) => `… and ${n} more`,
  },
};

/** An explicit `language:` in the card config wins; otherwise the user's Home
 *  Assistant language, with the browser as the last fallback (and the only
 *  thing available before `hass` is set). */
function isGerman(hass, config) {
  const forced = (config?.language || "auto").toLowerCase();
  if (forced === "de" || forced === "en") return forced === "de";
  const lang = (
    hass?.locale?.language ||
    hass?.language ||
    navigator.language ||
    "en"
  ).toLowerCase();
  return lang.startsWith("de");
}

function strings(hass, config) {
  return isGerman(hass, config) ? STRINGS.de : STRINGS.en;
}

const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** Entity names and ids come from the user's setup and land in innerHTML (and
 *  in title="…" attributes), so they have to be escaped. */
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => HTML_ESCAPES[char]);
}

const DOMAIN_ICONS = {
  light: "mdi:lightbulb",
  switch: "mdi:toggle-switch",
  sensor: "mdi:gauge",
  binary_sensor: "mdi:radiobox-marked",
  climate: "mdi:thermostat",
  lock: "mdi:lock",
  camera: "mdi:cctv",
  alarm_control_panel: "mdi:shield-home",
  cover: "mdi:window-shutter",
  media_player: "mdi:cast",
  fan: "mdi:fan",
  vacuum: "mdi:robot-vacuum",
  device_tracker: "mdi:account",
  update: "mdi:package-up",
};

function relativeAge(iso) {
  const started = new Date(iso).getTime();
  if (Number.isNaN(started)) return "";
  const minutes = Math.max(0, Math.round((Date.now() - started) / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

function timeOfDay(iso, german) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(german ? "de-DE" : "en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

class EntityWatchguardCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement(`${CARD_TAG}-editor`);
  }

  static getStubConfig() {
    return { type: `custom:${CARD_TAG}`, ignore_label: "offline" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._expanded = new Set();
    this._flash = new Map();
    this._config = {};
  }

  get _t() {
    return strings(this._hass, this._config);
  }

  setConfig(config) {
    this._config = {
      show_ok_domains: true,
      show_buttons: true,
      allow_ignore: true,
      ignore_label: "offline",
      ...config,
    };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 3 + this._expanded.size;
  }

  // --- data ----------------------------------------------------------
  _sensors() {
    if (!this._hass) return [];
    return Object.values(this._hass.states)
      .filter(
        (state) =>
          state.entity_id.startsWith("binary_sensor.entity_watchguard_") &&
          !state.entity_id.endsWith("_problem") &&
          state.attributes.status !== undefined
      )
      .map((state) => ({
        entityId: state.entity_id,
        domain: state.entity_id.replace("binary_sensor.entity_watchguard_", ""),
        count: state.attributes.count || 0,
        status: state.attributes.status,
        details: state.attributes.details || [],
        truncated: state.attributes.truncated,
      }))
      .sort((a, b) => b.count - a.count || a.domain.localeCompare(b.domain));
  }

  _button(suffix) {
    if (!this._hass) return undefined;
    // Tolerates renamed entity ids (…_check_now_2) and a renamed device.
    return Object.keys(this._hass.states).find(
      (id) => id.startsWith("button.") && id.includes(`entity_watchguard`) && id.includes(suffix)
    );
  }

  // --- actions -------------------------------------------------------
  async _press(suffix, element) {
    const entityId = this._button(suffix);
    if (!entityId) {
      this._banner(`${this._t.failed}: button.…_${suffix}`);
      return;
    }
    const label = element.textContent;
    element.disabled = true;
    element.textContent = "…";
    try {
      await this._hass.callService("button", "press", { entity_id: entityId });
      this._banner(suffix === "check_now" ? this._t.checked : this._t.recovering);
    } catch (err) {
      this._banner(`${this._t.failed}: ${err.message || err}`);
    } finally {
      element.disabled = false;
      element.textContent = label;
    }
  }

  _banner(text) {
    this._bannerText = text;
    this._render();
    clearTimeout(this._bannerTimer);
    this._bannerTimer = setTimeout(() => {
      this._bannerText = null;
      this._render();
    }, 4000);
  }

  _moreInfo(entityId) {
    const event = new Event("hass-more-info", { bubbles: true, composed: true });
    event.detail = { entityId };
    this.dispatchEvent(event);
  }

  async _ignore(entityId) {
    const labelName = this._config.ignore_label || "offline";
    try {
      // Labels are addressed by id, and the id only exists once the label
      // does — create it on first use instead of making the user do it.
      const labels = await this._hass.callWS({ type: "config/label_registry/list" });
      let label = labels.find(
        (item) =>
          item.label_id === labelName ||
          item.name.toLowerCase() === labelName.toLowerCase()
      );
      if (!label) {
        label = await this._hass.callWS({
          type: "config/label_registry/create",
          name: labelName,
        });
      }
      const entry = await this._hass.callWS({
        type: "config/entity_registry/get",
        entity_id: entityId,
      });
      const next = new Set(entry.labels || []);
      next.add(label.label_id);
      await this._hass.callWS({
        type: "config/entity_registry/update",
        entity_id: entityId,
        labels: [...next],
      });
      this._note(entityId, this._t.ignored);
    } catch (err) {
      // Most likely a YAML entity (not in the registry) or missing admin
      // rights — say so on the row instead of failing silently.
      this._note(entityId, `${this._t.failed}: ${err.message || err}`);
    }
  }

  _note(entityId, text) {
    this._flash.set(entityId, text);
    this._render();
    setTimeout(() => {
      this._flash.delete(entityId);
      this._render();
    }, 4000);
  }

  _toggle(domain) {
    if (this._expanded.has(domain)) this._expanded.delete(domain);
    else this._expanded.add(domain);
    this._render();
  }

  // --- rendering -----------------------------------------------------
  _render() {
    if (!this._hass) return;
    const T = this._t;
    const german = isGerman(this._hass, this._config);
    const sensors = this._sensors();
    const total = sensors.reduce((sum, sensor) => sum + sensor.count, 0);
    const warming = sensors.some((sensor) => sensor.status === "warming_up");
    const visible = this._config.show_ok_domains
      ? sensors
      : sensors.filter((sensor) => sensor.count > 0);

    // `hass` is set again on *any* state change in the system, several times a
    // second on a busy install, and each render replaced the card's whole
    // innerHTML. That had two visible effects: a click whose mousedown target
    // gets removed before mouseup never becomes a click event, so expanding a
    // domain only worked sometimes — and the row under the pointer lost and
    // regained :hover, which read as a flickering grey frame. So rebuild only
    // when something actually on screen changed. The minute bucket is there to
    // keep the relative ages ("5 min") ticking.
    const signature = JSON.stringify([
      this._config,
      german,
      visible,
      [...this._expanded].sort(),
      [...this._flash],
      this._bannerText,
      Math.floor(Date.now() / 60000),
    ]);
    if (signature === this._signature) return;
    this._signature = signature;

    if (!this.shadowRoot.querySelector("ha-card")) {
      this.shadowRoot.innerHTML = `<style>${EntityWatchguardCard.styles}</style><ha-card></ha-card>`;
    }
    const card = this.shadowRoot.querySelector("ha-card");

    let html = `
      <div class="header">
        <ha-icon icon="${total ? "mdi:shield-alert" : "mdi:shield-check"}"
                 class="${total ? "bad" : "good"}"></ha-icon>
        <div class="title">${esc(this._config.title ?? T.title)}</div>
        <div class="summary ${total ? "bad" : "good"}">
          ${warming ? T.warming : total ? `${total} ${T.offline}` : T.allOk}
        </div>
      </div>`;

    if (!sensors.length) {
      html += `<div class="empty">${T.noSensors}</div>`;
    }

    for (const sensor of visible) {
      const open = this._expanded.has(sensor.domain);
      const icon = DOMAIN_ICONS[sensor.domain] || "mdi:shape-outline";
      html += `
        <div class="row ${sensor.count ? "bad" : ""}" data-domain="${esc(sensor.domain)}">
          <ha-icon class="chevron" icon="${
            sensor.count ? (open ? "mdi:chevron-down" : "mdi:chevron-right") : "mdi:minus"
          }"></ha-icon>
          <ha-icon class="domain-icon" icon="${icon}"></ha-icon>
          <div class="domain">${esc(sensor.domain)}</div>
          <div class="badge ${sensor.count ? "bad" : "good"}">${sensor.count}</div>
        </div>`;

      if (!open || !sensor.count) continue;

      html += `<div class="details">`;
      for (const item of sensor.details) {
        const note = this._flash.get(item.entity_id);
        html += `
          <div class="detail">
            <div class="detail-main" data-entity="${esc(item.entity_id)}">
              <div class="name">
                <span class="name-text" title="${esc(item.name)}">${esc(item.name)}</span>
                ${item.given_up ? `<span class="tag">${T.gaveUp}</span>` : ""}
              </div>
              <div class="meta" title="${esc(item.entity_id)}">${esc(item.entity_id)}</div>
              <div class="meta">
                ${T.since} ${timeOfDay(item.since, german)} (${relativeAge(item.since)})
                ${item.attempts ? ` · ${item.attempts} ${T.attempts}` : ""}
              </div>
            </div>
            ${
              this._config.allow_ignore
                ? `<button class="ignore" data-ignore="${esc(item.entity_id)}"
                     title="${T.ignore(esc(this._config.ignore_label || "offline"))}">
                     <ha-icon icon="mdi:label-off-outline"></ha-icon>
                   </button>`
                : ""
            }
          </div>
          ${note ? `<div class="note">${esc(note)}</div>` : ""}`;
      }
      if (sensor.truncated) {
        html += `<div class="note">${T.more(sensor.count - sensor.details.length)}</div>`;
      }
      html += `</div>`;
    }

    if (this._bannerText) {
      html += `<div class="banner">${esc(this._bannerText)}</div>`;
    }

    if (this._config.show_buttons) {
      // Plain <button>s on purpose: mwc-button / ha-icon-button are frontend
      // internals and aren't reliably registered for custom cards.
      html += `
        <div class="actions">
          <button class="action" data-press="check_now">${T.check}</button>
          <button class="action" data-press="recover_now">${T.recover}</button>
        </div>`;
    }

    card.innerHTML = html;

    card.querySelectorAll("[data-domain]").forEach((element) =>
      element.addEventListener("click", () => this._toggle(element.dataset.domain))
    );
    card.querySelectorAll("[data-entity]").forEach((element) =>
      element.addEventListener("click", () => this._moreInfo(element.dataset.entity))
    );
    card.querySelectorAll("[data-ignore]").forEach((element) =>
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        this._ignore(element.dataset.ignore);
      })
    );
    card.querySelectorAll("[data-press]").forEach((element) =>
      element.addEventListener("click", () => this._press(element.dataset.press, element))
    );
  }
}

EntityWatchguardCard.styles = `
  ha-card { padding: 12px 8px 4px; }
  .header { display: flex; align-items: center; gap: 10px; padding: 0 8px 8px; }
  /* min-width: 0 everywhere a flex child holds text — without it a flex item
     refuses to shrink below its content and long names push out of the card. */
  .title {
    font-size: 1.1rem; font-weight: 500; flex: 1; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .summary { font-size: .9rem; flex: 0 0 auto; }
  .good { color: var(--success-color, #43a047); }
  .bad { color: var(--error-color, #db4437); }
  .empty { padding: 8px 12px; color: var(--secondary-text-color); }
  .row {
    display: flex; align-items: center; gap: 8px;
    padding: 6px 8px; border-radius: 8px; cursor: pointer;
  }
  .row:hover { background: var(--secondary-background-color); }
  .row .chevron { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
  .row .domain-icon { --mdc-icon-size: 20px; color: var(--state-icon-color, #44739e); }
  .domain {
    flex: 1; min-width: 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .badge {
    min-width: 24px; text-align: center; border-radius: 12px;
    padding: 1px 8px; font-size: .85rem;
    background: var(--secondary-background-color);
  }
  .badge.bad { background: var(--error-color, #db4437); color: #fff; }
  .details { padding: 0 8px 4px 36px; }
  .detail { display: flex; align-items: center; gap: 4px; }
  .detail-main { flex: 1; min-width: 0; padding: 4px 0; cursor: pointer; }
  .detail-main:hover .name-text { text-decoration: underline; }
  .name { display: flex; align-items: center; gap: 6px; min-width: 0; font-size: .95rem; }
  .name-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .meta {
    font-size: .75rem; color: var(--secondary-text-color);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .tag {
    flex: 0 0 auto;
    font-size: .7rem; padding: 1px 6px; border-radius: 8px;
    background: var(--error-color, #db4437); color: #fff;
  }
  .note { font-size: .75rem; color: var(--secondary-text-color); padding: 2px 0 6px; }
  .banner {
    margin: 4px 8px 0; padding: 6px 10px; border-radius: 8px;
    font-size: .85rem;
    background: var(--secondary-background-color);
    color: var(--primary-text-color);
  }
  .ignore {
    flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center;
    width: 32px; height: 32px; padding: 0;
    border: none; border-radius: 50%; cursor: pointer;
    background: none; color: var(--secondary-text-color);
    --mdc-icon-size: 20px;
  }
  .ignore:hover { background: var(--secondary-background-color); color: var(--primary-text-color); }
  .actions {
    display: flex; justify-content: flex-end; gap: 8px;
    border-top: 1px solid var(--divider-color); margin-top: 8px; padding: 8px 4px;
  }
  .action {
    font: inherit; font-size: .9rem; font-weight: 500;
    padding: 6px 14px; border-radius: 18px; cursor: pointer;
    border: 1px solid var(--divider-color);
    background: none; color: var(--primary-color, #03a9f4);
  }
  .action:hover:not([disabled]) { background: var(--secondary-background-color); }
  .action[disabled] { opacity: .5; cursor: default; }
`;

class EntityWatchguardCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  _emit(changes) {
    this._config = { ...this._config, ...changes };
    const event = new CustomEvent("config-changed", {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    });
    this.dispatchEvent(event);
  }

  _render() {
    if (!this._config) return;
    const conf = this._config;
    const T = strings(this._hass, this._config);
    const DE = isGerman(this._hass, this._config);
    // Native inputs, same reasoning as the card itself: no dependency on
    // frontend-internal elements that may not be registered.
    const check = (key, label) => `
      <label class="ewg-row">
        <input type="checkbox" id="${key}" ${conf[key] !== false ? "checked" : ""}>
        <span>${label}</span>
      </label>`;

    this.innerHTML = `
      <style>
        .ewg-form { display: flex; flex-direction: column; gap: 12px; padding: 8px 0; }
        .ewg-field { display: flex; flex-direction: column; gap: 4px; }
        .ewg-field span { font-size: .8rem; color: var(--secondary-text-color); }
        .ewg-field input, .ewg-field select {
          font: inherit; padding: 8px; border-radius: 4px;
          border: 1px solid var(--divider-color);
          background: var(--card-background-color); color: var(--primary-text-color);
        }
        .ewg-row { display: flex; align-items: center; gap: 8px; cursor: pointer; }
      </style>
      <div class="ewg-form">
        <label class="ewg-field">
          <span>${DE ? "Titel" : "Title"}</span>
          <input type="text" id="title" value="${conf.title ?? T.title}">
        </label>
        <label class="ewg-field">
          <span>${DE ? "Label zum Ignorieren" : "Label used for ignoring"}</span>
          <input type="text" id="ignore_label" value="${conf.ignore_label ?? "offline"}">
        </label>
        <label class="ewg-field">
          <span>${DE ? "Sprache" : "Language"}</span>
          <select id="language">
            <option value="auto" ${(conf.language ?? "auto") === "auto" ? "selected" : ""}>
              ${DE ? "Automatisch (Home Assistant)" : "Automatic (Home Assistant)"}
            </option>
            <option value="de" ${conf.language === "de" ? "selected" : ""}>Deutsch</option>
            <option value="en" ${conf.language === "en" ? "selected" : ""}>English</option>
          </select>
        </label>
        ${check("show_ok_domains", DE ? "Saubere Domains anzeigen" : "Show clean domains")}
        ${check("show_buttons", DE ? "Buttons anzeigen" : "Show buttons")}
        ${check("allow_ignore", DE ? "Ignorieren erlauben" : "Allow ignoring")}
      </div>`;

    this.querySelectorAll('input[type="text"]').forEach((field) =>
      field.addEventListener("input", () => this._emit({ [field.id]: field.value }))
    );
    this.querySelectorAll('input[type="checkbox"]').forEach((toggle) =>
      toggle.addEventListener("change", () => this._emit({ [toggle.id]: toggle.checked }))
    );
    this.querySelectorAll("select").forEach((select) =>
      select.addEventListener("change", () => {
        this._emit({ [select.id]: select.value });
        this._render(); // the editor's own labels follow the choice
      })
    );
  }
}

customElements.define(CARD_TAG, EntityWatchguardCard);
customElements.define(`${CARD_TAG}-editor`, EntityWatchguardCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TAG,
  name: "Entity Watchguard",
  description: isGerman(null, null)
    ? "Nicht verfügbare Entities pro Domain, mit Wiederherstellungs-Buttons"
    : "Unavailable entities per domain, with recovery buttons",
  preview: true,
});
