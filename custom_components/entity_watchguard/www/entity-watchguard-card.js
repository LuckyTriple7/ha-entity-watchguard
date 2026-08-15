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

const DE = (navigator.language || "en").toLowerCase().startsWith("de");
const T = DE
  ? {
      title: "Entity Watchguard",
      offline: "nicht verfügbar",
      allOk: "Alles verfügbar",
      warming: "Startphase läuft …",
      check: "Jetzt prüfen",
      recover: "Wiederherstellen",
      since: "seit",
      attempts: "Versuche",
      gaveUp: "aufgegeben",
      ignore: (label) => `Ignorieren (Label „${label}")`,
      ignored: "Label gesetzt",
      failed: "Fehlgeschlagen",
      noSensors: "Keine Entity-Watchguard-Sensoren gefunden.",
      more: (n) => `… und ${n} weitere`,
    }
  : {
      title: "Entity Watchguard",
      offline: "unavailable",
      allOk: "All available",
      warming: "Warming up …",
      check: "Check now",
      recover: "Recover now",
      since: "since",
      attempts: "attempts",
      gaveUp: "gave up",
      ignore: (label) => `Ignore (label "${label}")`,
      ignored: "Label applied",
      failed: "Failed",
      noSensors: "No Entity Watchguard sensors found.",
      more: (n) => `… and ${n} more`,
    };

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

function timeOfDay(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(DE ? "de-DE" : "en-GB", {
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

  setConfig(config) {
    this._config = {
      title: T.title,
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
    return this._hass
      ? Object.keys(this._hass.states).find((id) =>
          id === `button.entity_watchguard_${suffix}`
        )
      : undefined;
  }

  // --- actions -------------------------------------------------------
  _press(suffix) {
    const entityId = this._button(suffix);
    if (entityId) {
      this._hass.callService("button", "press", { entity_id: entityId });
    }
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
      this._note(entityId, T.ignored);
    } catch (err) {
      // Most likely a YAML entity (not in the registry) or missing admin
      // rights — say so on the row instead of failing silently.
      this._note(entityId, `${T.failed}: ${err.message || err}`);
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
    const sensors = this._sensors();
    const total = sensors.reduce((sum, sensor) => sum + sensor.count, 0);
    const warming = sensors.some((sensor) => sensor.status === "warming_up");
    const visible = this._config.show_ok_domains
      ? sensors
      : sensors.filter((sensor) => sensor.count > 0);

    if (!this.shadowRoot.querySelector("ha-card")) {
      this.shadowRoot.innerHTML = `<style>${EntityWatchguardCard.styles}</style><ha-card></ha-card>`;
    }
    const card = this.shadowRoot.querySelector("ha-card");

    let html = `
      <div class="header">
        <ha-icon icon="${total ? "mdi:shield-alert" : "mdi:shield-check"}"
                 class="${total ? "bad" : "good"}"></ha-icon>
        <div class="title">${this._config.title}</div>
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
        <div class="row ${sensor.count ? "bad" : ""}" data-domain="${sensor.domain}">
          <ha-icon class="chevron" icon="${
            sensor.count ? (open ? "mdi:chevron-down" : "mdi:chevron-right") : "mdi:minus"
          }"></ha-icon>
          <ha-icon class="domain-icon" icon="${icon}"></ha-icon>
          <div class="domain">${sensor.domain}</div>
          <div class="badge ${sensor.count ? "bad" : "good"}">${sensor.count}</div>
        </div>`;

      if (!open || !sensor.count) continue;

      html += `<div class="details">`;
      for (const item of sensor.details) {
        const note = this._flash.get(item.entity_id);
        html += `
          <div class="detail">
            <div class="detail-main" data-entity="${item.entity_id}">
              <div class="name">
                ${item.name}
                ${item.given_up ? `<span class="tag">${T.gaveUp}</span>` : ""}
              </div>
              <div class="meta">
                ${item.entity_id} · ${T.since} ${timeOfDay(item.since)}
                (${relativeAge(item.since)})
                ${item.attempts ? ` · ${item.attempts} ${T.attempts}` : ""}
              </div>
            </div>
            ${
              this._config.allow_ignore
                ? `<ha-icon-button class="ignore" data-ignore="${item.entity_id}"
                     title="${T.ignore(this._config.ignore_label || "offline")}">
                     <ha-icon icon="mdi:label-off-outline"></ha-icon>
                   </ha-icon-button>`
                : ""
            }
          </div>
          ${note ? `<div class="note">${note}</div>` : ""}`;
      }
      if (sensor.truncated) {
        html += `<div class="note">${T.more(sensor.count - sensor.details.length)}</div>`;
      }
      html += `</div>`;
    }

    if (this._config.show_buttons) {
      html += `
        <div class="actions">
          <mwc-button data-press="check_now">${T.check}</mwc-button>
          <mwc-button data-press="recover_now">${T.recover}</mwc-button>
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
      element.addEventListener("click", () => this._press(element.dataset.press))
    );
  }
}

EntityWatchguardCard.styles = `
  ha-card { padding: 12px 8px 4px; }
  .header { display: flex; align-items: center; gap: 10px; padding: 0 8px 8px; }
  .title { font-size: 1.1rem; font-weight: 500; flex: 1; }
  .summary { font-size: .9rem; }
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
  .domain { flex: 1; }
  .badge {
    min-width: 24px; text-align: center; border-radius: 12px;
    padding: 1px 8px; font-size: .85rem;
    background: var(--secondary-background-color);
  }
  .badge.bad { background: var(--error-color, #db4437); color: #fff; }
  .details { padding: 0 8px 4px 36px; }
  .detail { display: flex; align-items: center; gap: 4px; }
  .detail-main { flex: 1; padding: 4px 0; cursor: pointer; }
  .detail-main:hover .name { text-decoration: underline; }
  .name { font-size: .95rem; }
  .meta { font-size: .75rem; color: var(--secondary-text-color); }
  .tag {
    font-size: .7rem; margin-left: 6px; padding: 1px 6px; border-radius: 8px;
    background: var(--error-color, #db4437); color: #fff;
  }
  .note { font-size: .75rem; color: var(--secondary-text-color); padding: 2px 0 6px; }
  .ignore { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
  .actions {
    display: flex; justify-content: flex-end; gap: 4px;
    border-top: 1px solid var(--divider-color); margin-top: 8px; padding: 4px;
  }
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
    this.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:12px;padding:8px 0;">
        <ha-textfield label="${DE ? "Titel" : "Title"}"
          value="${conf.title ?? T.title}" id="title"></ha-textfield>
        <ha-textfield label="${DE ? "Label zum Ignorieren" : "Label used for ignoring"}"
          value="${conf.ignore_label ?? "offline"}" id="ignore_label"></ha-textfield>
        <ha-formfield label="${DE ? "Saubere Domains anzeigen" : "Show clean domains"}">
          <ha-switch id="show_ok_domains" ${conf.show_ok_domains !== false ? "checked" : ""}></ha-switch>
        </ha-formfield>
        <ha-formfield label="${DE ? "Buttons anzeigen" : "Show buttons"}">
          <ha-switch id="show_buttons" ${conf.show_buttons !== false ? "checked" : ""}></ha-switch>
        </ha-formfield>
        <ha-formfield label="${DE ? "Ignorieren erlauben" : "Allow ignoring"}">
          <ha-switch id="allow_ignore" ${conf.allow_ignore !== false ? "checked" : ""}></ha-switch>
        </ha-formfield>
      </div>`;

    this.querySelectorAll("ha-textfield").forEach((field) =>
      field.addEventListener("input", () => this._emit({ [field.id]: field.value }))
    );
    this.querySelectorAll("ha-switch").forEach((toggle) =>
      toggle.addEventListener("change", () => this._emit({ [toggle.id]: toggle.checked }))
    );
  }
}

customElements.define(CARD_TAG, EntityWatchguardCard);
customElements.define(`${CARD_TAG}-editor`, EntityWatchguardCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: CARD_TAG,
  name: "Entity Watchguard",
  description: DE
    ? "Nicht verfügbare Entities pro Domain, mit Wiederherstellungs-Buttons"
    : "Unavailable entities per domain, with recovery buttons",
  preview: true,
});
