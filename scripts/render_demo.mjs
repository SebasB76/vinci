// Captures docs/images/pantallas/pantallas.html frame by frame: calls its render(t) through the DevTools protocol of a
// headless Chromium started with --remote-debugging-port. Usage: node render_demo.mjs <port> <url> <out-dir> <fps>
import { writeFileSync } from "node:fs";

const [port, url, outDir, fps] = process.argv.slice(2);
const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(pages.find((p) => p.type === "page").webSocketDebuggerUrl);
await new Promise((resolve) => { ws.onopen = resolve; });
let seq = 0;
const waiting = new Map();
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  waiting.get(msg.id)?.(msg);
};
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq;
  waiting.set(id, (msg) => (msg.error ? reject(new Error(`${method}: ${msg.error.message}`)) : resolve(msg.result)));
  ws.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expression) => (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result.value;

await send("Emulation.setDeviceMetricsOverride", { width: 1200, height: 720, deviceScaleFactor: 2, mobile: false });
await send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }] });
await send("Page.navigate", { url });
for (let tries = 0; !(await evaluate("document.readyState === 'complete' && typeof render === 'function'")); tries++) {
  if (tries > 100) throw new Error("the page did not load");
  await new Promise((r) => setTimeout(r, 100));
}
await evaluate("document.fonts.ready.then(() => true)");
const total = await evaluate("TOTAL");
const frames = Math.round((total * fps) / 1000);
for (let f = 0; f < frames; f++) {
  await evaluate(`render(${(f * 1000) / fps})`);
  const { data } = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(`${outDir}/${String(f).padStart(4, "0")}.png`, Buffer.from(data, "base64"));
}
console.log(`${frames} frames`);
ws.close();
