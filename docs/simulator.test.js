// Checks the browser simulator's core logic with Node: `node docs/simulator.test.js`
const fs = require("fs"), path = require("path"), assert = require("assert");
const html = fs.readFileSync(path.join(__dirname, "index.html"), "utf8");
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
