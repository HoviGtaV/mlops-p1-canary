// Builds report/slides.pptx  (run: node build_deck.js)
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const FIG = path.join(__dirname, "..", "figures");
const OUT = path.join(__dirname, "..", "slides.pptx");

const THEME = {
  name: "P1 Canary",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1B2A30", lt1: "FFFFFF", dk2: "0B3C49", lt2: "EEF4F5",
    accent1: "0E7C86", accent2: "E4574F", accent3: "2E9E62", accent4: "E9A23B",
    accent5: "5B7F8A", accent6: "9BB8BF", hlink: "0E7C86", folHlink: "5B7F8A",
  },
};
const HEX = THEME.colors;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "P1 - Canary rollout of a readmission model";
pres.author = "MLOps P1 team";
const C = pres.SchemeColor;

// ------------------------------------------------------------------ layouts
pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 2.0, w: 11.7, h: 1.9,
        fontSize: 40, bold: true, color: C.background1, valign: "bottom", align: "left", fontFace: THEME.headFontFace },
        text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 4.15, w: 11.7, h: 1.4,
        fontSize: 18, color: "CFE3E6", valign: "top" }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CLOSING_DARK",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 0.6, w: 11.7, h: 1.0,
        fontSize: 38, bold: true, color: C.background1, valign: "middle", align: "left", fontFace: THEME.headFontFace },
        text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  margin: [0.5, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.95,
        fontSize: 34, bold: true, color: C.text2, valign: "middle", fontFace: THEME.headFontFace },
        text: "" } },
    { text: { text: "P1 · Canary rollout · MLOps ESIB 2026",
        options: { x: 0.6, y: 7.0, w: 6, h: 0.3, fontSize: 10, color: "7A8F95", margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: "7A8F95", align: "right" },
});

// ------------------------------------------------------------------ helpers
function pngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20) };
}
function img(slide, name, x, y, maxW, maxH, alt) {
  const file = path.join(FIG, name);
  const s = pngSize(file);
  let w = maxW, h = (maxW * s.h) / s.w;
  if (h > maxH) { h = maxH; w = (maxH * s.w) / s.h; }
  slide.addImage({ path: file, x, y, w, h, altText: alt, objectName: name });
  return { w, h };
}
function shadow() {
  return { type: "outer", color: "0B3C49", opacity: 0.12, blur: 6, offset: 2, angle: 90 };
}
function card(slide, x, y, w, h, opts = {}) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.12, fill: { color: opts.fill || C.background2 },
    line: { color: opts.fill || C.background2, width: 0 }, shadow: opts.shadow === false ? undefined : shadow(),
    objectName: opts.name || "card",
  });
}
function badge(slide, x, y, label, color, d = 0.55) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: color || C.accent1 },
    line: { color: color || C.accent1, width: 0 }, objectName: "badge " + label });
  slide.addText(label, { x, y, w: d, h: d, align: "center", valign: "middle", fontSize: d > 0.6 ? 18 : 14,
    bold: true, color: C.background1, margin: 0, isTextBox: true, fontFace: THEME.headFontFace });
}
function text(slide, t, o) { slide.addText(t, Object.assign({ isTextBox: true, margin: 0, valign: "top" }, o)); }
function content(title, section) {
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  return s;
}
function arrow(slide, x1, y1, x2, y2, color) {
  slide.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: Math.min(y1, y2),
    w: Math.abs(x2 - x1) || 0.001, h: Math.abs(y2 - y1) || 0.001,
    flipH: x2 < x1, flipV: y2 < y1,
    line: { color: color || "5B7F8A", width: 1.75, endArrowType: "triangle" }, objectName: "arrow" });
}

// ================================================================== slides
// 1 ---------------------------------------------------------------- title
pres.addSection({ title: "Story" });
let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Story" });
s.addText("Shipping a better readmission model without breaking the service", { placeholder: "title" });
s.addText("P1 · Canary release on UCI Diabetes 130-US hospitals\nMLOps · ESIB · Fall 2026", { placeholder: "body" });
s.addNotes("Introduce the project: P1, a canary release. A hospital already uses a model to predict 30-day readmissions; we want to replace it with a better one without risking the service. Over the next slides: the two models, how the canary works, our system, the four guardrails, what happened when we broke v2 on purpose, and the three report questions.");

// 2 ---------------------------------------------------------------- v1 vs v2
s = content("v2 is better offline, but ten times heavier", "Story");
const colX = [0.6, 6.85];
const models = [
  { name: "v1 · in production", sub: "Logistic regression · @champion", auc: "0.663", ms: "1 ms", color: C.accent5 },
  { name: "v2 · candidate", sub: "Gradient boosting · @challenger", auc: "0.676", ms: "10 ms", color: C.accent1 },
];
models.forEach((m, i) => {
  const x = colX[i];
  card(s, x, 1.55, 5.9, 3.9);
  text(s, m.name, { x: x + 0.4, y: 1.8, w: 5.1, h: 0.5, fontSize: 22, bold: true, color: m.color, fontFace: THEME.headFontFace });
  text(s, m.sub, { x: x + 0.4, y: 2.3, w: 5.1, h: 0.4, fontSize: 15, color: C.text1 });
  text(s, m.auc, { x: x + 0.4, y: 2.95, w: 2.5, h: 1.0, fontSize: 54, bold: true, color: m.color, fontFace: THEME.headFontFace });
  text(s, "validation AUC", { x: x + 0.4, y: 3.95, w: 2.5, h: 0.4, fontSize: 13, color: "5B6B70" });
  text(s, m.ms, { x: x + 3.1, y: 2.95, w: 2.4, h: 1.0, fontSize: 54, bold: true, color: m.color, fontFace: THEME.headFontFace });
  text(s, "per prediction (median)", { x: x + 3.1, y: 3.95, w: 2.5, h: 0.4, fontSize: 13, color: "5B6B70" });
  text(s, i === 0 ? "Test AUC 0.653 · p99 2.4 ms" : "Test AUC 0.663 · p99 29.5 ms",
    { x: x + 0.4, y: 4.6, w: 5.1, h: 0.4, fontSize: 14, color: C.text1 });
});
text(s, [
  { text: "Data: ", options: { bold: true } },
  { text: "99,343 encounters (deaths and hospice removed), target readmitted < 30 days (11.4%), split by patient 70/15/15 with seed 42. The test split is the live traffic." },
], { x: 0.6, y: 5.85, w: 12.1, h: 0.8, fontSize: 15, color: C.text1 });
s.addNotes("v2 wins offline on validation and test AUC, and on recall in the top 15 percent on validation (on test the two are equal at 31 percent). But it costs about 10 ms per prediction against 1 ms for v1. Splitting by patient matters: a patient with several stays must not appear in both train and test. We removed deaths and hospice discharges because they cannot be readmitted.");

// 3 ---------------------------------------------------------------- canary plan
pres.addSection({ title: "System" });
s = content("A canary moves patients to v2 in four checked steps", "System");
const steps = ["1%", "5%", "25%", "100%"];
steps.forEach((p, i) => {
  const x = 0.6 + i * 3.15;
  card(s, x, 1.7, 2.6, 2.3, { fill: i === 3 ? C.accent3 : C.accent1 });
  text(s, p, { x, y: 1.95, w: 2.6, h: 1.0, fontSize: 48, bold: true, color: C.background1, align: "center", fontFace: THEME.headFontFace });
  text(s, i === 3 ? "of patients on v2:\nrollout passed" : "of patients on v2", { x: x + 0.2, y: 3.0, w: 2.2, h: 0.8, fontSize: 15, color: C.background1, align: "center" });
  if (i < 3) arrow(s, x + 2.65, 2.85, x + 3.1, 2.85, "0B3C49");
});
card(s, 0.6, 4.45, 12.1, 0.95, { fill: C.background2, shadow: false });
text(s, [
  { text: "At every step, every 5 s: ", options: { bold: true, color: C.text2 } },
  { text: "read Prometheus, check 4 guardrails. Move on after ≥ 30 s and 400 / 700 / 1,000 / 1,500 v2 requests." },
], { x: 0.9, y: 4.62, w: 11.5, h: 0.65, fontSize: 16, color: C.text1, valign: "middle" });
card(s, 0.6, 5.65, 12.1, 0.95, { fill: "FBE3E1", shadow: false });
text(s, [
  { text: "Rollback: ", options: { bold: true, color: C.accent2 } },
  { text: "a guardrail fails on 2 checks in a row → weight back to 0%, v1 serves everyone. Registry aliases never move." },
], { x: 0.9, y: 5.82, w: 11.5, h: 0.65, fontSize: 16, color: C.text1, valign: "middle" });
s.addNotes("The idea of a canary: expose only a few patients first. Users are assigned by a hash of their patient id, so a patient always gets the same model, and raising the weight keeps the patients already on v2. Each step needs a minimum time and a minimum number of v2 requests so the statistics mean something. A rollback only sets the weight to zero; v1 stays the champion in the registry.");

// 4 ---------------------------------------------------------------- architecture
s = content("Everything runs in Docker Compose on one laptop", "System");
function box(x, y, w, h, title, sub, fill) {
  card(s, x, y, w, h, { fill: fill || C.background2 });
  const dark = fill && fill !== C.background2;
  text(s, title, { x: x + 0.15, y: y + 0.12, w: w - 0.3, h: 0.4, fontSize: 16, bold: true, color: dark ? C.background1 : C.text2, align: "center" });
  text(s, sub, { x: x + 0.15, y: y + 0.52, w: w - 0.3, h: h - 0.6, fontSize: 12, color: dark ? "E6F2F3" : C.text1, align: "center" });
}
box(0.6, 2.3, 2.3, 1.3, "Simulator", "replays test patients\n150 requests/s");
box(3.5, 2.3, 2.5, 1.3, "Router (FastAPI)", "sticky hash of patient id\nweight w on v2", C.accent1);
box(6.7, 1.55, 2.6, 1.15, "variant-a · v1", "loads @champion");
box(6.7, 3.2, 2.6, 1.15, "variant-b · v2", "loads @challenger\n+ failure flags");
box(10.0, 2.3, 2.7, 1.3, "MLflow", "tracking + model registry\naliases, tags");
box(6.7, 5.25, 2.6, 1.15, "Prometheus", "scrapes /metrics every 2 s");
box(10.0, 5.25, 2.7, 1.15, "Grafana", "v1 and v2 side by side");
box(3.5, 5.25, 2.5, 1.15, "Controller", "1% → 100% loop\nguardrails, rollback", C.text2);
arrow(s, 2.95, 2.95, 3.45, 2.95);
arrow(s, 6.05, 2.75, 6.65, 2.15);
arrow(s, 6.05, 3.15, 6.65, 3.75);
arrow(s, 9.35, 2.15, 9.95, 2.75);
arrow(s, 9.35, 3.75, 9.95, 3.2);
arrow(s, 7.95, 4.4, 7.95, 5.2);
arrow(s, 9.35, 5.8, 9.95, 5.8);
arrow(s, 6.65, 5.8, 6.05, 5.8);
arrow(s, 4.75, 5.2, 4.75, 3.65, "E4574F");
text(s, "both variants: same image, different alias", { x: 6.7, y: 2.72, w: 2.6, h: 0.45, fontSize: 11, italic: true, color: "5B6B70", align: "center" });
text(s, "set weight / rollback", { x: 2.2, y: 4.25, w: 2.45, h: 0.4, fontSize: 11, italic: true, color: C.accent2, align: "right" });
text(s, "Every app metric has a variant label", { x: 0.6, y: 1.5, w: 5.4, h: 0.4, fontSize: 14, bold: true, color: C.accent1 });
s.addNotes("Walk the request path: the simulator replays test patients, the router decides A or B and measures what users see, the two variants are literally the same container with a different registry alias. Prometheus scrapes everything; Grafana shows v1 and v2 side by side. The controller reads Prometheus through its HTTP API and changes the router weight. Each variant runs 8 worker processes so v2 can take 100 percent of the traffic.");

// 5 ---------------------------------------------------------------- guardrails
pres.addSection({ title: "Guardrails" });
s = content("Four guardrails decide if v2 may go on", "Guardrails");
const rails = [
  ["1", "Error rate", "One-sided two-proportion z-test vs v1: p < 0.001, gap ≥ 1 point, confirmed by an exact binomial test", "catches: random HTTP 500s"],
  ["2", "p99 latency", "p99(v2) ≤ 1.1 × (p99(v1) + 1.5 × v2's offline extra cost) ≈ 52 ms, from 300 requests", "catches: extra latency"],
  ["3", "Score PSI", "Distribution of v2's predicted risk vs v1's: PSI ≤ 0.15, from 5% traffic and 500 requests", "catches: silent schema bug"],
  ["4", "Invalid scores", "Share of NaN or out-of-range probabilities ≤ 0.1%", "catches: broken model output"],
];
rails.forEach((r, i) => {
  const x = 0.6 + (i % 2) * 6.15, y = 1.55 + Math.floor(i / 2) * 2.65;
  card(s, x, y, 5.95, 2.4);
  badge(s, x + 0.3, y + 0.3, r[0]);
  text(s, r[1], { x: x + 1.05, y: y + 0.33, w: 4.6, h: 0.5, fontSize: 20, bold: true, color: C.text2, fontFace: THEME.headFontFace });
  text(s, r[2], { x: x + 0.3, y: y + 1.0, w: 5.35, h: 0.95, fontSize: 15, color: C.text1 });
  text(s, r[3], { x: x + 0.3, y: y + 1.92, w: 5.35, h: 0.35, fontSize: 13, italic: true, color: C.accent1 });
});
s.addNotes("Each guardrail is aimed at one failure. Error rate: the z-test the subject asks for, plus an exact test because errors are rare. Latency: v2 is allowed its known extra cost, anything beyond trips it. PSI: compares the shape of the predicted risk distributions, the only thing that sees a bug that still returns HTTP 200. Invalid scores: NaN or out of range. A breach must repeat on two consecutive checks.");

// 6 ---------------------------------------------------------------- results
pres.addSection({ title: "Results" });
s = content("Healthy v2 passed; every failure was rolled back", "Results");
const hdr = (t) => ({ text: t, options: { bold: true, color: "FFFFFF", fill: { color: HEX.dk2 } } });
const out = (t, ok) => ({ text: t, options: { bold: true, color: ok ? HEX.accent3 : HEX.accent2 } });
s.addTable([
  [hdr("Scenario (flag on v2)"), hdr("Outcome"), hdr("Caught by"), hdr("When")],
  ["Healthy (2 runs)", out("PASSED · 100% on v2", true), "—", "≈ 7 min each"],
  ["+50 ms latency", out("ROLLED BACK", false), "p99 88 ms > 52 ms", "1% · 314 requests · 203 s"],
  ["5% HTTP 500 errors", out("ROLLED BACK", false), "error rate, z = 10.0", "1% · 65 requests · 46 s"],
  ["Silent schema bug (HTTP 200)", out("ROLLED BACK", false), "score PSI 0.187 > 0.15", "5% · 546 requests · 354 s"],
], { x: 0.6, y: 1.6, w: 12.1, colW: [3.4, 2.8, 2.9, 3.0], rowH: 0.62, fontSize: 16,
  color: HEX.dk1, border: { type: "solid", color: "D5E2E5", pt: 1 }, fill: { color: "FFFFFF" },
  valign: "middle", margin: [0, 0.12, 0, 0.12], objectName: "results table" });
card(s, 0.6, 5.15, 12.1, 1.35, { fill: C.background2, shadow: false });
text(s, [
  { text: "Each failure was caught by the guardrail built for it, ", options: { bold: true, color: C.text2 } },
  { text: "at 1% or 5% traffic: at most ~960 v2 requests were exposed (the schema bug, which only PSI can see). During a rollback the registry aliases never moved." },
], { x: 0.9, y: 5.3, w: 11.5, h: 1.05, fontSize: 16, color: C.text1, valign: "middle" });
s.addNotes("This is the headline result. The healthy v2 passed twice. Each injected failure was stopped by the right guardrail: latency at 1 percent, errors at 1 percent in 46 seconds, and the schema bug at 5 percent, because PSI only starts there (we will see why).");

// 7 ---------------------------------------------------------------- healthy run
s = content("A healthy rollout, as Grafana shows it", "Results");
img(s, "grafana_healthy.png", 0.6, 1.45, 7.6, 5.35, "Grafana dashboard during a healthy rollout");
const hs = [["PASSED", "1% → 5% → 25% → 100% in 7 min", C.accent3],
            ["36–46 ms", "v2 p99 at 100%, limit 52 ms", C.accent1],
            ["0.02–0.08", "score PSI, threshold 0.15", C.accent1]];
hs.forEach((h, i) => {
  const y = 1.55 + i * 1.75;
  card(s, 8.6, y, 4.1, 1.5);
  text(s, h[0], { x: 8.85, y: y + 0.15, w: 3.7, h: 0.75, fontSize: 36, bold: true, color: h[2], fontFace: THEME.headFontFace });
  text(s, h[1], { x: 8.85, y: y + 0.92, w: 3.7, h: 0.45, fontSize: 14, color: C.text1 });
});
s.addNotes("Live dashboard of a healthy run. Point at the canary weight going up step by step, the orange v2 lines next to the blue v1 lines, latency higher for v2 but under its limit, and the PSI well below the threshold. Then the rollout state turns to passed.");

// 8 ---------------------------------------------------------------- schema bug
s = content("The silent schema bug: HTTP 200, wrong risk", "Results");
img(s, "grafana_schema.png", 0.6, 1.45, 7.6, 5.35, "Grafana dashboard during the schema-bug rollout");
const sb = [["200 OK", "every request answered; error and latency guardrails never fired", C.accent1],
            ["11.2% → 8.9%", "offline mean risk; test AUC 0.663 → 0.623", C.accent4],
            ["PSI 0.187", "> 0.15: rolled back at 5% traffic", C.accent2]];
sb.forEach((h, i) => {
  const y = 1.55 + i * 1.75;
  card(s, 8.6, y, 4.1, 1.5);
  text(s, h[0], { x: 8.85, y: y + 0.15, w: 3.7, h: 0.75, fontSize: 32, bold: true, color: h[2], fontFace: THEME.headFontFace });
  text(s, h[1], { x: 8.85, y: y + 0.92, w: 3.7, h: 0.5, fontSize: 14, color: C.text1 });
});
s.addNotes("The most dangerous failure. Upstream, the column number_inpatient was renamed. The service does not crash: the missing column is imputed, so the status codes and latency look perfect. But it is the strongest predictor, so frequent patients now look low risk. Only the shape of the score distribution reveals it, through PSI.");

// 9 ---------------------------------------------------------------- Q1
pres.addSection({ title: "Report questions" });
s = content("Q1 · A 5% error rate is caught after ~65 requests", "Report questions");
card(s, 0.6, 1.55, 4.6, 5.1);
text(s, "65", { x: 0.9, y: 1.75, w: 4.0, h: 1.3, fontSize: 72, bold: true, color: C.accent2, fontFace: THEME.headFontFace });
text(s, "v2 requests before rollback, live, at 1% traffic (46 s)", { x: 0.9, y: 3.05, w: 4.0, h: 0.7, fontSize: 15, color: C.text1 });
const q1 = [["47", "power formula, α = 0.001, 80% power"], ["67", "median of 4,000 simulated canaries"], ["548", "needed if the bug added only +1 point"]];
q1.forEach((q, i) => {
  const y = 3.95 + i * 0.85;
  text(s, q[0], { x: 0.9, y, w: 1.1, h: 0.6, fontSize: 26, bold: true, color: C.accent1, fontFace: THEME.headFontFace, valign: "middle" });
  text(s, q[1], { x: 2.05, y, w: 2.95, h: 0.6, fontSize: 13, color: C.text1, valign: "middle" });
});
img(s, "q1_detection_curve.png", 5.55, 1.6, 7.15, 4.9, "Detection probability vs requests on v2");
s.addNotes("Baseline error 0.2 percent, v2 with the bug fails 5.2 percent. Because v1 gets 99 times more traffic, its rate is almost known. The power formula says 47 v2 requests; our full rule with minimum samples, exact test and two consecutive checks needs a median of 67 in simulation. Live we measured 65 requests, 46 seconds. Smaller bugs take much longer: plus one point needs 548 requests.");

// 10 --------------------------------------------------------------- Q2
s = content("Q2 · Repeated checks roll back healthy models", "Report questions");
const q2labels = ["Literal rules (p99 ≤ 1.1×v1, α 0.05)", "+ allow v2's known extra latency", "+ minimum samples per guardrail",
  "+ PSI threshold = baseline + 0.10", "+ α 0.01 and gap ≥ 1 point", "+ 2 consecutive breaches", "+ exact binomial confirmation",
  "+ PSI from 5% traffic, threshold 0.15", "+ α 0.001 for ~85 checks (shipped)"];
const q2vals = [100, 100, 93.3, 88.7, 65.4, 49.7, 43.0, 4.3, 1.0];
s.addChart(pres.charts.BAR, [{ name: "False rollbacks of a healthy v2 (%)", labels: q2labels.slice().reverse(), values: q2vals.slice().reverse() }], {
  x: 0.6, y: 1.45, w: 8.0, h: 5.3, barDir: "bar", varyColors: true,
  chartColors: ["2E9E62", "9BB8BF", "9BB8BF", "9BB8BF", "9BB8BF", "9BB8BF", "9BB8BF", "9BB8BF", "E4574F"],
  showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.0\"%\"", dataLabelFontSize: 12,
  dataLabelColor: "1B2A30", dataLabelFontFace: "+mn-lt",
  catAxisLabelFontSize: 12, catAxisLabelColor: "1B2A30", catAxisLabelFontFace: "+mn-lt",
  valAxisHidden: true, valAxisMaxVal: 115, valAxisMinVal: 0, valGridLine: { style: "none" }, catGridLine: { style: "none" },
  showLegend: false, showTitle: false, barGapWidthPct: 45, objectName: "Q2 chart",
});
card(s, 8.95, 1.55, 3.75, 5.1);
text(s, "100% → 1%", { x: 9.2, y: 1.75, w: 3.3, h: 0.9, fontSize: 40, bold: true, color: C.accent3, fontFace: THEME.headFontFace });
text(s, "false rollbacks of a healthy v2, 1,000 simulated rollouts per rule", { x: 9.2, y: 2.65, w: 3.3, h: 0.8, fontSize: 14, color: C.text1 });
text(s, [
  { text: "Why: ", options: { bold: true, color: C.text2 } },
  { text: "~85 checks per rollout. At 5% false positives per check: 1 − 0.95⁸⁵ ≈ 99%.", options: { breakLine: true } },
  { text: " ", options: { breakLine: true } },
  { text: "Live: ", options: { bold: true, color: C.text2 } },
  { text: "5 of our first 6 healthy runs were rolled back. With the shipped rule: 2 of 2 passed." },
], { x: 9.2, y: 3.6, w: 3.3, h: 2.9, fontSize: 14, color: C.text1 });
s.addNotes("This happened to us for real: five of our first six healthy runs were rolled back, one by each weakness. The simulation bootstraps real requests from our healthy runs and replays the controller's schedule. Starting from the literal rules, every fix brings the false rollback rate down, from 100 percent to 1 percent. The root cause is repeated testing: checking 60 times at 5 percent each almost guarantees a false alarm.");

// 11 --------------------------------------------------------------- PSI
s = content("Why the PSI guardrail waits until 5% traffic", "Report questions");
const psiCards = [["1% traffic", "~100 patients on v2", "67%", "false alarms", "99%", "bug detected", C.accent2],
                  ["5% traffic", "~500 patients on v2", "0.5%", "false alarms", "96%", "bug detected", C.accent3],
                  ["25% traffic", "~2,600 patients on v2", "0%", "false alarms", "93%", "bug detected", C.accent3]];
psiCards.forEach((p, i) => {
  const x = 0.6 + i * 4.1;
  card(s, x, 1.5, 3.9, 2.2);
  text(s, p[0], { x: x + 0.25, y: 1.65, w: 3.4, h: 0.45, fontSize: 20, bold: true, color: C.text2, fontFace: THEME.headFontFace });
  text(s, p[1], { x: x + 0.25, y: 2.1, w: 3.4, h: 0.35, fontSize: 13, color: "5B6B70" });
  text(s, p[2], { x: x + 0.25, y: 2.5, w: 1.8, h: 0.7, fontSize: 32, bold: true, color: p[6], fontFace: THEME.headFontFace });
  text(s, p[3], { x: x + 0.25, y: 3.2, w: 1.8, h: 0.35, fontSize: 12, color: C.text1 });
  text(s, p[4], { x: x + 2.05, y: 2.5, w: 1.7, h: 0.7, fontSize: 32, bold: true, color: C.accent1, fontFace: THEME.headFontFace });
  text(s, p[5], { x: x + 2.05, y: 3.2, w: 1.7, h: 0.35, fontSize: 12, color: C.text1 });
});
img(s, "psi_calibration.png", 0.6, 3.95, 12.1, 2.9, "Simulated PSI of healthy and buggy v2 by traffic share");
s.addNotes("At 1 percent, v2 sees only about a hundred patients. Their risk distribution differs from everybody else's just because they are different patients, so even a healthy v2 has a large PSI. We simulated thousands of random patient subsets: at 1 percent PSI cannot separate healthy from buggy. From 5 percent it can, with a threshold of 0.15.");

// 12 --------------------------------------------------------------- Q3
s = content("Q3 · A canary proves v2 is safe, not better", "Report questions");
const q3 = [["Late outcome", "\"Better\" = fewer readmissions within 30 days. A canary lasts minutes."],
            ["Tiny effect, tiny sample", "AUC gain ≈ 0.01; v2 sees a few hundred requests at 1–5% traffic."],
            ["Not an experiment design", "Shifting traffic share, short steps, hash-selected users, no planned sample size."],
            ["\"Not worse\" tests", "One-sided guardrails: passing means no evidence of harm, never evidence of gain."]];
q3.forEach((q, i) => {
  const y = 1.55 + i * 1.3;
  badge(s, 0.6, y + 0.15, String(i + 1));
  text(s, q[0], { x: 1.4, y: y + 0.05, w: 6.3, h: 0.45, fontSize: 19, bold: true, color: C.text2, fontFace: THEME.headFontFace });
  text(s, q[1], { x: 1.4, y: y + 0.52, w: 6.3, h: 0.6, fontSize: 15, color: C.text1 });
});
card(s, 8.3, 1.55, 4.4, 2.35, { fill: C.accent1 });
text(s, "Canary", { x: 8.6, y: 1.75, w: 3.8, h: 0.6, fontSize: 26, bold: true, color: C.background1, fontFace: THEME.headFontFace });
text(s, "Is v2 safe to serve?\nErrors, latency, score shape. Minutes.", { x: 8.6, y: 2.4, w: 3.8, h: 1.3, fontSize: 15, color: C.background1 });
card(s, 8.3, 4.2, 4.4, 2.35, { fill: C.text2 });
text(s, "A/B test", { x: 8.6, y: 4.4, w: 3.8, h: 0.6, fontSize: 26, bold: true, color: C.background1, fontFace: THEME.headFontFace });
text(s, "Is v2 better for patients?\nPlanned sample size, fixed duration, business metric.", { x: 8.6, y: 5.05, w: 3.8, h: 1.3, fontSize: 15, color: C.background1 });
s.addNotes("Four reasons the canary cannot say v2 is better. The real outcome comes a month later; the gain is tiny for the sample the canary sees; the canary is not a controlled experiment; and its tests only ask whether v2 is worse. Our evidence that v2 is better is offline AUC; proving it in production is the job of an A/B test, which is project P2.");

// 13 --------------------------------------------------------------- conclusion
pres.addSection({ title: "Conclusion" });
s = pres.addSlide({ masterName: "CLOSING_DARK", sectionTitle: "Conclusion" });
s.addText("What we take away", { placeholder: "title" });
const take = [["Safe rollout works", "Healthy v2 reached 100%; each injected failure was stopped at 1% or 5% traffic by the right guardrail."],
              ["Statistics set the rules", "Small samples and repeated checks caused 5 false rollbacks; each fix is measured in the report."],
              ["Next step", "An A/B test on readmissions before promoting v2 to @champion, and drift alerts on input features."]];
take.forEach((t, i) => {
  const x = 0.8 + i * 4.0;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.1, w: 3.7, h: 3.0, rectRadius: 0.12,
    fill: { color: "134D5C" }, line: { color: "134D5C", width: 0 }, objectName: "takeaway " + (i + 1) });
  badge(s, x + 0.3, 2.4, String(i + 1), i === 2 ? C.accent4 : C.accent1);
  text(s, t[0], { x: x + 0.3, y: 3.15, w: 3.15, h: 0.5, fontSize: 20, bold: true, color: "FFFFFF", fontFace: THEME.headFontFace });
  text(s, t[1], { x: x + 0.3, y: 3.75, w: 3.15, h: 1.25, fontSize: 15, color: "D6E8EB" });
});
text(s, "Questions? A live run of the error scenario takes under a minute.", { x: 0.8, y: 5.75, w: 11.7, h: 0.6, fontSize: 20, italic: true, color: "CFE3E6" });
s.addNotes("Close on three points: the rollout mechanism works end to end; the statistics are what make it trustworthy, and our false alarms taught us that; and the next step is an A/B test before v2 becomes the champion. Then open the floor for questions, and offer a live run of the errors scenario, which takes under a minute.");

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote " + OUT);
})();
