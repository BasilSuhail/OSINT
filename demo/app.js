/* The demo map. One snapshot file in, one map out, no network beyond the
 * basemap tiles.
 *
 * The symbol rules here are copies of the console's — the same hazard colours,
 * the same aircraft silhouettes, the same hull shapes. Copies rather than
 * imports because this page is plain JavaScript served by a static host with
 * no build step, and a demo that needs a toolchain is a demo nobody opens. The
 * cost is that the two can drift; the snapshot script and this file live in
 * the same repository so they drift together, and nothing here is a claim
 * about anything except what one console showed one afternoon.
 */

const SNAPSHOT = "data/snapshot.json";
const STYLE = "https://tiles.openfreemap.org/styles/dark";

/* The rail's own colours, as the console defines them. */
const HAZARDS = [
  { key: "EQ", label: "Earthquakes", hex: "#ef4444" },
  { key: "TC", label: "Cyclones", hex: "#f97316" },
  { key: "FL", label: "Floods", hex: "#38bdf8" },
  { key: "WF", label: "Wildfires", hex: "#eab308" },
  { key: "ICE", label: "Ice & snow", hex: "#67e8f9" },
  { key: "VO", label: "Volcanoes", hex: "#d946ef" },
  { key: "DR", label: "Droughts", hex: "#a16207" },
  { key: "other", label: "Everything else", hex: "#a3a3a3" },
];

const AIRCRAFT_COLORS = { military: "#7dd3fc", watched: "#fcd34d", distress: "#ef4444" };

const AIR_ROWS = [
  { key: "military", label: "Military air", hex: AIRCRAFT_COLORS.military },
  { key: "watched", label: "Watchlist", hex: AIRCRAFT_COLORS.watched },
];

const SEA_ROWS = [
  { key: "cargo", label: "Cargo" },
  { key: "tanker", label: "Tankers" },
  { key: "passenger", label: "Passenger" },
  { key: "fishing", label: "Fishing" },
  { key: "pleasure", label: "Pleasure" },
  { key: "service", label: "Service" },
  { key: "other", label: "Unclassified" },
];

const VESSEL_TEAL = "#5eead4";
const VESSEL_SUSPECT = "#fcd34d";

/* Which disaster a row is, from the same fields the console reads. */
function hazardKind(ev) {
  const source = (ev.source || "").toLowerCase();
  if (source.includes("usgs")) return "EQ";
  if (source.includes("firms")) return "WF";
  const payload = ev.payload || {};
  const type = String(payload.event_type || "").toUpperCase();
  if (["EQ", "WF", "TC", "FL", "VO", "DR", "ICE"].includes(type)) return type;
  const categories = Array.isArray(payload.categories)
    ? payload.categories.map((c) => String(c).toLowerCase())
    : [];
  if (categories.some((c) => /ice|snow/.test(c))) return "ICE";
  const title = String(payload.title || payload.headline || "").toLowerCase();
  if (/storm|typhoon|cyclone|hurricane/.test(title)) return "TC";
  if (title.includes("volcano")) return "VO";
  if (title.includes("flood")) return "FL";
  if (title.includes("drought")) return "DR";
  if (title.includes("wildfire") || title.includes("fire")) return "WF";
  if (/ice|iceberg|snow|glacier/.test(title)) return "ICE";
  return "other";
}

const HAZARD_ICON = {
  EQ: '<path d="M2 12h3l2-6 3 12 3-9 2 3h5" fill="none" stroke="#0a0a0a" stroke-width="2.2" stroke-linejoin="round"/>',
  TC: '<path d="M3 8h12a3 3 0 1 0-3-3M3 12h16a3 3 0 1 1-3 3M3 16h9" fill="none" stroke="#0a0a0a" stroke-width="2.2" stroke-linecap="round"/>',
  FL: '<path d="M12 3s6 7 6 11a6 6 0 0 1-12 0c0-4 6-11 6-11z" fill="#0a0a0a"/>',
  WF: '<path d="M12 2s5 5 5 10a5 5 0 0 1-10 0c0-2 1-3 2-5 1 3 3 2 3 0 0-2 0-3 0-5z" fill="#0a0a0a"/>',
  ICE: '<path d="M12 2v20M3 7l18 10M21 7L3 17" fill="none" stroke="#0a0a0a" stroke-width="2.2" stroke-linecap="round"/>',
  VO: '<path d="M12 4l9 16H3z" fill="none" stroke="#0a0a0a" stroke-width="2.4" stroke-linejoin="round"/>',
  DR: '<circle cx="12" cy="12" r="5" fill="#0a0a0a"/><path d="M12 1v3M12 20v3M1 12h3M20 12h3M4 4l2 2M18 18l2 2M20 4l-2 2M6 18l-2 2" stroke="#0a0a0a" stroke-width="2.2" stroke-linecap="round"/>',
  other: '<circle cx="12" cy="12" r="4" fill="#0a0a0a"/>',
};

/* Aircraft silhouettes, nose up, exactly as the console draws them. */
const FIXED_WING =
  "M12 1.2 L12.9 4.6 L13.1 9 L22.4 14.6 L22.4 15.9 L13.4 13 L12.8 17.4 " +
  "L12.6 18.2 L16.4 21.2 L16.4 22.2 L12 20.6 L7.6 22.2 L7.6 21.2 L11.4 18.2 " +
  "L11.2 17.4 L10.6 13 L1.6 15.9 L1.6 14.6 L10.9 9 L11.1 4.6 Z";
const ROTOR_BODY =
  "M12 2.9 C14.2 2.9 15.7 5.3 15.7 8.4 C15.7 10.9 14.8 12.9 13.4 13.8 " +
  "L13 20 L11 20 L10.6 13.8 C9.2 12.9 8.3 10.9 8.3 8.4 C8.3 5.3 9.8 2.9 12 2.9 Z";
const ROTOR_BLADES = "M1.6 2.6 L22.4 14.2 M22.4 2.6 L1.6 14.2";
const DELTA = "M12 2.6 L19 20.4 L12 16.4 L5 20.4 Z";

const HULL_UNDER_WAY = "M12 2.2 L16.4 9.4 L16.4 20.4 L7.6 20.4 L7.6 9.4 Z";
const HULL_STOPPED = "M12 6.6 L15.6 11 L15.6 18 L8.4 18 L8.4 11 Z";

const ROTORCRAFT_NAMES = new Set([
  "A109", "A119", "A129", "A139", "A149", "A169", "A189", "AS32", "AS3B", "AS50",
  "AS55", "AS65", "ALO2", "ALO3", "LAMA", "GAZL", "PUMA", "BK17", "S61", "S64",
  "S70", "S76", "S92", "B06", "B212", "B407", "B412", "B429", "B505", "R22",
  "R44", "R66", "EXPL", "NH90", "EH10", "LYNX", "WASP", "SCOU", "TIGR", "W3", "V22",
]);

function silhouette(type) {
  const code = (type || "").trim().toUpperCase();
  if (!code) return "unknown";
  if (ROTORCRAFT_NAMES.has(code)) return "rotorcraft";
  if (!code.startsWith("H25")) {
    for (const prefix of ["H", "EC", "MI", "KA"]) {
      if (code.startsWith(prefix) && /^\d/.test(code.slice(prefix.length))) return "rotorcraft";
    }
  }
  return "fixed-wing";
}

function svg(inner, { size = 16, rotate = null, color = "#fff" } = {}) {
  const spin = rotate == null ? "" : ` style="transform:rotate(${rotate}deg)"`;
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="${color}"${spin}>${inner}</svg>`;
}

function aircraftMarkup(a) {
  const colour = a.watch ? AIRCRAFT_COLORS.watched : AIRCRAFT_COLORS.military;
  if (a.kind === "distress") {
    return `<span class="mark"><svg width="10" height="10" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="${AIRCRAFT_COLORS.distress}"/></svg></span>`;
  }
  const shape = silhouette(a.type);
  const body =
    shape === "rotorcraft"
      ? `<path d="${ROTOR_BODY}"/><rect x="9.2" y="19.5" width="5.6" height="1.2" rx="0.6"/><ellipse cx="15.1" cy="20.1" rx="0.9" ry="1.6"/><path d="${ROTOR_BLADES}" stroke="${colour}" stroke-opacity="0.9" stroke-width="1.5" stroke-linecap="round"/>`
      : `<path d="${shape === "fixed-wing" ? FIXED_WING : DELTA}"/>`;
  return `<span class="mark">${svg(body, { rotate: a.track ?? null, color: colour })}</span>`;
}

function vesselMarkup(v) {
  const suspect = Boolean(v.position_suspect);
  const underWay = !["at anchor", "moored", "aground"].includes(v.nav_status) && (v.speed_kt || 0) >= 0.5;
  const bearing = v.heading != null ? v.heading : v.course;
  const path = underWay ? HULL_UNDER_WAY : HULL_STOPPED;
  const colour = suspect ? VESSEL_SUSPECT : VESSEL_TEAL;
  const shape = suspect
    ? `<path d="${path}" fill="none" stroke="${colour}" stroke-width="2" stroke-dasharray="3 2" stroke-linejoin="round"/>`
    : `<path d="${path}"/>`;
  return `<span class="mark">${svg(shape, {
    size: 12,
    rotate: underWay && bearing != null ? bearing : null,
    color: colour,
  })}</span>`;
}

function hazardMarkup(kind, colour) {
  return `<span class="mark"><span class="chip" style="background:${colour};box-shadow:0 0 3px ${colour}aa">${svg(
    HAZARD_ICON[kind] || HAZARD_ICON.other,
    { size: 9 },
  )}</span></span>`;
}

/* Severity colour, the console's magnitude and alert-level bands. */
function hazardColour(ev, kind) {
  const payload = ev.payload || {};
  if (kind === "ICE") return "#67e8f9";
  if (kind === "EQ") {
    const mag = Number(payload.magnitude || 0);
    if (mag >= 6) return "#ef4444";
    if (mag >= 4.5) return "#f97316";
    return "#22c55e";
  }
  const alert = String(payload.alert_level || "").toLowerCase();
  if (alert === "red") return "#ef4444";
  if (alert === "orange") return "#f97316";
  return "#22c55e";
}

/* What a mark is called, with no free text to call it by.
 *
 * The snapshot deliberately carries no titles: a headline names people, and
 * this file sits in a public repository. So a card names the thing by what it
 * is and links to whoever published it — which is the honest half of a
 * headline anyway.
 */
function title(ev, kind) {
  const payload = ev.payload || {};
  const label = (HAZARDS.find((h) => h.key === kind) || {}).label || "Event";
  const magnitude = payload.magnitude ? ` M${payload.magnitude}` : "";
  const where = ev.country ? ` · ${ev.country}` : "";
  return `${label.replace(/s$/, "")}${magnitude}${where}`;
}

function when(iso) {
  if (!iso) return null;
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

const state = {
  map: null,
  data: null,
  markers: [],
  on: {
    hazard: Object.fromEntries(HAZARDS.map((h) => [h.key, true])),
    air: Object.fromEntries(AIR_ROWS.map((r) => [r.key, true])),
    sea: Object.fromEntries(SEA_ROWS.map((r) => [r.key, true])),
  },
};

function card(html) {
  document.getElementById("card-body").innerHTML = html;
  document.getElementById("card").hidden = false;
}

function facts(pairs) {
  return `<dl>${pairs
    .filter(([, value]) => value != null && value !== "")
    .map(([key, value]) => `<dt>${key}</dt><dd>${value}</dd>`)
    .join("")}</dl>`;
}

function eventCard(ev, kind) {
  const payload = ev.payload || {};
  const label = (HAZARDS.find((h) => h.key === kind) || {}).label || kind;
  const link = payload.link;
  card(
    `<h3>${title(ev, kind)}</h3><p class="kind">${label} · ${ev.source}</p>` +
      facts([
        ["when", when(ev.occurred_at)],
        ["magnitude", payload.magnitude],
        ["alert", payload.alert_level],
        ["country", ev.country],
        ["severity", ev.severity == null ? null : Number(ev.severity).toFixed(2)],
        ["position", `${ev.lat.toFixed(2)}, ${ev.lon.toFixed(2)}`],
      ]) +
      (link
        ? `<p class="caveat"><a href="${link}" target="_blank" rel="noreferrer" style="color:inherit">what the source published →</a></p>`
        : "") +
      `<p class="caveat">Recorded at the moment of the snapshot. This file carries no headlines — a headline names people, and it is published from a public repository — so a mark is named by what it is and linked to whoever reported it.</p>`,
  );
}

function aircraftCard(a) {
  card(
    `<h3>${a.callsign || a.registration || (a.hex || "").toUpperCase() || "Unknown aircraft"}</h3>` +
      `<p class="kind">${a.watch ? a.watch.label : "flagged military by the feed"}</p>` +
      facts([
        ["type", a.type],
        ["role", a.role && a.role !== "other" ? a.role : null],
        ["altitude", a.alt_ft == null ? null : `${Math.round(a.alt_ft).toLocaleString()} ft`],
        ["speed", a.speed_kt == null ? null : `${Math.round(a.speed_kt)} kt`],
        ["track", a.track == null ? null : `${Math.round(a.track)}°`],
        ["registration", a.registration],
        ["hex", (a.hex || "").toUpperCase()],
      ]) +
      `<p class="caveat">Presence, not evidence — where a transponder said it was when the snapshot was taken. The military flag is the feed's, and covers state transports too.</p>`,
  );
}

function vesselCard(v) {
  const suspect = v.position_suspect;
  card(
    `<h3>${v.mmsi ? `MMSI ${v.mmsi}` : "Unknown vessel"}</h3>` +
      `<p class="kind">${v.category === "other" ? "type not transmitted" : v.category}</p>` +
      (suspect
        ? `<p class="caveat" style="color:${VESSEL_SUSPECT}">This position is not believed: ${
            suspect === "speed" ? "a reported speed no vessel can reach" : "several moving vessels on one position"
          }. Something is interfering with the transmission or imitating it.</p>`
        : "") +
      facts([
        ["status", v.nav_status],
        ["speed", v.speed_kt == null ? null : `${v.speed_kt.toFixed(1)} kt`],
        ["heading", (v.heading ?? v.course) == null ? null : `${Math.round(v.heading ?? v.course)}°`],
        ["MMSI", v.mmsi],
        ["position", `${v.lat.toFixed(2)}, ${v.lon.toFixed(2)}`],
      ]) +
      `<p class="caveat">AIS heard by shore receivers. The live console also shows the ship's name and where it says it is bound; this file leaves free text out.</p>`,
  );
}

function marker(lngLat, html, onClick) {
  const el = document.createElement("div");
  el.innerHTML = html;
  el.addEventListener("click", (e) => {
    e.stopPropagation();
    onClick();
  });
  return new maplibregl.Marker({ element: el }).setLngLat(lngLat).addTo(state.map);
}

function draw() {
  for (const m of state.markers) m.remove();
  state.markers = [];
  const { events, aircraft, vessels } = state.data;

  for (const ev of events) {
    const kind = hazardKind(ev);
    if (!state.on.hazard[kind]) continue;
    state.markers.push(
      marker([ev.lon, ev.lat], hazardMarkup(kind, hazardColour(ev, kind)), () => eventCard(ev, kind)),
    );
  }

  for (const a of aircraft) {
    const row = a.watch ? "watched" : "military";
    if (!state.on.air[row]) continue;
    state.markers.push(marker([a.lon, a.lat], aircraftMarkup(a), () => aircraftCard(a)));
  }

  for (const v of vessels) {
    if (!state.on.sea[v.category]) continue;
    state.markers.push(marker([v.lon, v.lat], vesselMarkup(v), () => vesselCard(v)));
  }
}

function rows(container, definitions, group, counts, colourFor) {
  container.innerHTML = "";
  for (const def of definitions) {
    const button = document.createElement("button");
    button.className = "row";
    button.type = "button";
    button.setAttribute("aria-pressed", String(state.on[group][def.key]));
    button.innerHTML =
      `<span class="swatch" style="background:${colourFor(def)}"></span>` +
      `<span class="label">${def.label}</span>` +
      `<span class="count">${(counts[def.key] || 0).toLocaleString()}</span>`;
    button.addEventListener("click", () => {
      state.on[group][def.key] = !state.on[group][def.key];
      button.setAttribute("aria-pressed", String(state.on[group][def.key]));
      draw();
    });
    container.appendChild(button);
  }
}

function tally(items, key) {
  const counts = {};
  for (const item of items) {
    const bucket = key(item);
    counts[bucket] = (counts[bucket] || 0) + 1;
  }
  return counts;
}

async function start() {
  state.map = new maplibregl.Map({
    container: "map",
    style: STYLE,
    center: [12, 45],
    zoom: 2.2,
    attributionControl: { compact: true },
  });
  state.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
  state.map.on("click", () => {
    document.getElementById("card").hidden = true;
  });
  document.getElementById("card-close").addEventListener("click", () => {
    document.getElementById("card").hidden = true;
  });

  let data;
  try {
    const response = await fetch(SNAPSHOT);
    if (!response.ok) throw new Error(String(response.status));
    data = await response.json();
  } catch {
    document.getElementById("taken").textContent =
      "the snapshot file did not load — the map below is empty for that reason, not because the world is";
    return;
  }
  state.data = data;

  const taken = when(data.taken_at);
  document.getElementById("taken").textContent = taken
    ? `Everything here is from ${taken}. Nothing refreshes.`
    : "Everything here is from one moment. Nothing refreshes.";

  rows(
    document.getElementById("hazard-rows"),
    HAZARDS,
    "hazard",
    tally(data.events, hazardKind),
    (d) => d.hex,
  );
  rows(
    document.getElementById("air-rows"),
    AIR_ROWS,
    "air",
    tally(data.aircraft, (a) => (a.watch ? "watched" : "military")),
    (d) => d.hex,
  );
  rows(
    document.getElementById("sea-rows"),
    SEA_ROWS,
    "sea",
    tally(data.vessels, (v) => v.category),
    () => VESSEL_TEAL,
  );

  const suspect = data.vessels.filter((v) => v.position_suspect).length;
  document.getElementById("air-note").textContent =
    `${(data.heard?.aircraft ?? data.counts.aircraft).toLocaleString()} aircraft were airborne and broadcasting when this was taken.` +
    (suspect ? ` ${suspect} vessels below were transmitting positions the console does not believe.` : "");

  //: What was left out, said plainly. Drawing a fraction of the fires without
  //: saying so is a claim about how many fires there are.
  const heard = data.heard || {};
  const dropped = ["events", "vessels"]
    .filter((key) => (heard[key] ?? 0) > data.counts[key])
    .map((key) => `${data.counts[key].toLocaleString()} of ${heard[key].toLocaleString()} ${key}`);
  if (dropped.length) {
    document.getElementById("about").insertAdjacentHTML(
      "beforeend",
      `<br /><br />Thinned to keep the page quick: it draws ${dropped.join(
        " and ",
      )}. Every vessel with a position the console disbelieves was kept.`,
    );
  }

  state.map.on("load", draw);
}

start();
