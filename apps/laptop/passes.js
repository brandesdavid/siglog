const TLE_URL =
  "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=tle";

const TARGETS = [
  { label: "METEOR-M 2", names: ["METEOR-M 2"], freqMhz: 137.1, decoder: "lrpt" },
  { label: "METEOR-M2 3", names: ["METEOR-M2 3"], freqMhz: 137.9, decoder: "lrpt" },
  { label: "METEOR-M2 4", names: ["METEOR-M2 4"], freqMhz: 137.9, decoder: "lrpt" },
];

function parseTle(text) {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const out = [];
  for (let i = 0; i + 2 < lines.length; i += 3) {
    const name = lines[i];
    if (!lines[i + 1].startsWith("1 ") || !lines[i + 2].startsWith("2 ")) continue;
    out.push({
      name,
      satrec: satellite.twoline2satrec(lines[i + 1], lines[i + 2]),
    });
  }
  return out;
}

function resolveSat(byName, target) {
  for (const n of target.names) {
    if (byName[n]) return byName[n];
  }
  const key = target.label.toUpperCase();
  for (const [name, sat] of Object.entries(byName)) {
    if (name.toUpperCase().includes(key)) return sat;
  }
  return null;
}

function elevationDeg(satrec, lat, lng, date) {
  const pv = satellite.propagate(satrec, date);
  if (!pv.position) return -90;
  const gmst = satellite.gstime(date);
  const posEcf = satellite.eciToEcf(pv.position, gmst);
  const observer = {
    latitude: satellite.degreesToRadians(lat),
    longitude: satellite.degreesToRadians(lng),
    height: 0,
  };
  const look = satellite.ecfToLookAngles(observer, posEcf);
  return satellite.degrees * look.elevation;
}

function subpoint(satrec, date) {
  const pv = satellite.propagate(satrec, date);
  if (!pv.position) return null;
  const gmst = satellite.gstime(date);
  const gd = satellite.eciToGeodetic(pv.position, gmst);
  return {
    lat: satellite.degrees * gd.latitude,
    lng: satellite.degrees * gd.longitude,
  };
}

function groundTrack(satrec, aos, los, steps = 48) {
  const pts = [];
  const t0 = aos.getTime();
  const t1 = los.getTime();
  for (let i = 0; i < steps; i++) {
    const frac = i / Math.max(steps - 1, 1);
    const t = new Date(t0 + (t1 - t0) * frac);
    const p = subpoint(satrec, t);
    if (p) pts.push({ lat: Math.round(p.lat * 1e5) / 1e5, lng: Math.round(p.lng * 1e5) / 1e5 });
  }
  return pts;
}

function findPassesForSat(satrec, lat, lng, hours, minEl) {
  const stepMs = 20 * 1000;
  const end = Date.now() + hours * 3600 * 1000;
  const passes = [];
  let t = Date.now();
  let above = elevationDeg(satrec, lat, lng, new Date(t)) >= minEl;

  while (t < end) {
    const el = elevationDeg(satrec, lat, lng, new Date(t));
    if (!above && el >= minEl) {
      let aos = t;
      let los = t;
      let maxEl = el;
      let scan = t;
      while (scan < end) {
        const e2 = elevationDeg(satrec, lat, lng, new Date(scan));
        if (e2 >= minEl) {
          los = scan;
          if (e2 > maxEl) maxEl = e2;
        } else if (scan > aos + stepMs) {
          break;
        }
        scan += stepMs;
      }
      const aosDate = new Date(aos);
      const losDate = new Date(los);
      if (losDate > new Date()) {
        passes.push({ aos: aosDate, los: losDate, maxEl, satrec });
      }
      t = scan + stepMs;
      above = false;
      continue;
    }
    above = el >= minEl;
    t += stepMs;
  }
  return passes;
}

async function fetchTle() {
  const res = await fetch(TLE_URL, { headers: { Accept: "text/plain" } });
  if (!res.ok) throw new Error(`TLE HTTP ${res.status}`);
  return res.text();
}

async function computePasses(lat, lng, hours = 48, minEl = 15) {
  const text = await fetchTle();
  const parsed = parseTle(text);
  const byName = Object.fromEntries(parsed.map((s) => [s.name, s]));
  const now = Date.now();
  const out = [];

  for (const target of TARGETS) {
    const sat = resolveSat(byName, target);
    if (!sat) continue;
    const raw = findPassesForSat(sat.satrec, lat, lng, hours, minEl);
    for (const p of raw) {
      const startInMin = Math.max(0, Math.floor((p.aos.getTime() - now) / 60000));
      out.push({
        name: target.label,
        aos: p.aos.toISOString(),
        los: p.los.toISOString(),
        maxElevation: Math.round(p.maxEl * 10) / 10,
        freqMhz: target.freqMhz,
        antennaCm: 54,
        startInMin,
        decoder: target.decoder,
        track: groundTrack(sat.satrec, p.aos, p.los),
      });
    }
  }

  out.sort((a, b) => new Date(a.aos) - new Date(b.aos));
  return {
    observer: { lat, lng },
    passes: out,
    source: "celestrak",
    computedAt: new Date().toISOString(),
  };
}
