// Checks the browser simulator's core logic with Node: `node docs/simulator.test.js`
const fs = require("fs"), path = require("path"), assert = require("assert");
const html = fs.readFileSync(path.join(__dirname, "season.html"), "utf8");
const core = html.slice(html.indexOf("// ===== KS-CORE-START"), html.indexOf("// ===== KS-CORE-END"));
const KS = new Function(core + "\nreturn KS;")();

const base = { crop: "tomato", stage: "mid", soil: "loam", area: 1000, lpm: 300, method: "furrow",
               days: 60, rainShare: 0.15, seed: 7, every: 3, fixedMinutes: 90 };
const r = KS.simulate(base);
assert(Math.abs(r.field.taw - 91) < 0.5, "loam tomato root zone holds ~91 mm");
assert.equal(JSON.stringify(KS.simulate(base).days.map(d => d.advice.status)),
             JSON.stringify(r.days.map(d => d.advice.status)), "same seed, same season");

const f = { ...r.field, eff: 0.6, area: 1000, lpm: 300 };
const dry = { et0: 4.8, fRain: 0, prob: 5 }, wet = { et0: 3, fRain: 60, prob: 90 };
assert.equal(KS.advise(f, 0.5 * f.taw, dry, dry).status, "IRRIGATE_NOW");
assert.equal(KS.advise(f, 0.55 * f.taw, wet, dry).status, "SKIP_RAIN");
assert.equal(KS.advise(f, 0.1 * f.taw, dry, dry).status, "OK");
for (const lang of ["or", "hi", "en"]) assert(!KS.message(KS.advise(f, 0.5 * f.taw, dry, dry), 50, lang).includes("{"));

for (const crop of Object.keys(KS.CROPS)) for (const soil of Object.keys(KS.SOILS)) for (const method of Object.keys(KS.EFF)) {
  const q = KS.simulate({ ...base, crop, soil, method, days: 30 });
  for (const p of q.farmers.ks.series) assert(p.pct >= 0 && p.pct <= 110.0001, `${crop}/${soil}/${method} out of range`);
}
console.log(`simulator OK: KrishiSense ${(r.farmers.ks.litres / 1000).toFixed(0)} m3, ` +
            `fixed schedule ${(r.farmers.fixed.litres / 1000).toFixed(0)} m3 over ${base.days} days`);

// ---- live farm engine (docs/farm-engine.js) ----
const KSFarm = require("./farm-engine.js");
const farm = new KSFarm.Farm({ seed: 7, days: 30 });
farm.run(30 * 24);
assert(farm.finished && !farm.tick(), "season ends after 30 days");
const byId = Object.fromEntries(farm.summary().map(s => [s.station_id, s]));
assert(byId["sim-chilli"].max_buffered_readings >= 45, "12 h outage is buffered on the station");
assert(byId["sim-groundnut"].pump_runs >= 1, "automatic pump control acted");
assert(byId["sim-tomato"].pump_runs >= 1, "farmer followed the advice");
const en = farm.alerts.filter(a => a.recipient === "SIMULATED-en");
assert(en.some(a => a.station_id === "sim-chilli" && a.status === "SENSOR_STALE"), "outage raised a no-data alert");
const perStatus = {};
for (const a of en) perStatus[a.station_id + a.status] = (perStatus[a.station_id + a.status] || 0) + 1;
for (const [k, n] of Object.entries(perStatus)) assert(n <= 30 * 24 / 20 + 1, `alert spam: ${k} ${n}`);
assert(farm.alerts.every(a => !a.text.includes("{")), "all messages fully rendered");
const info = farm.api("/api/v1/stations");
assert(info.simulated && info.stations.length === 3);
for (const st of info.stations) {
  const h = farm.api(`/api/v1/history?station_id=${st.station_id}&days=7`);
  assert(h.length > 300 && h.every(p => p.water_pct >= 0 && p.water_pct <= 110));
  assert(typeof farm.api(`/api/v1/advice?station_id=${st.station_id}`).status === "string");
}
console.log("live farm OK:", farm.summary().map(s => `${s.station_id} ${s.water_m3} m3, ${s.pump_runs} runs`).join("; "));

// ---- shared Season (used by the hub so every view shows the same farm) ----
const S = new KSFarm.Season({ seed: 7, days: 30 });
assert(S.farm.ts > KSFarm.SIM_EPOCH && S.events.length >= 0, "season starts warmed up");
S.speed = 24; for (let i = 0; i < 200; i++) S.advance(0.1);       // ~20 simulated days
const tLate = S.farm.ts;
assert(S.events.some(e => e.kind === "net") && S.events.some(e => e.kind === "pump"), "events recorded");
const statusLate = S.farm.api("/api/v1/advice?station_id=sim-tomato").available_water_pct;
S.seek(KSFarm.SIM_EPOCH + 3 * 86400);
assert(S.farm.ts <= KSFarm.SIM_EPOCH + 3 * 86400 && S.farm.ts > KSFarm.SIM_EPOCH + 2.9 * 86400, "seek back");
S.seek(tLate);
assert.equal(S.farm.api("/api/v1/advice?station_id=sim-tomato").available_water_pct, statusLate, "replay is deterministic");
let selected = null; S.on("select", id => selected = id); S.select("sim-chilli");
assert.equal(selected, "sim-chilli");
console.log("season OK:", KSFarm.fmtSim(S.farm.ts), `${S.events.length} events`);
