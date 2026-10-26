export const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>ICM acceptance fixture</title>
<style>
body { font-family: system-ui, sans-serif; margin: 0 auto; padding: 24px; max-width: 640px; color: #17263a; }
form { display: flex; flex-direction: column; gap: 12px; } input, button { font: inherit; padding: 12px; }
button { background: #173d70; color: white; border: 0; border-radius: 6px; cursor: pointer; }
li { padding: 12px 0; overflow-wrap: anywhere; } #status { min-height: 24px; }
</style></head><body><main><h1>Saved items</h1>
<p>A synthetic browser and API acceptance fixture.</p>
<form><label for="value">Item value</label><input id="value" required autocomplete="off">
<button type="submit">Save item</button></form><p id="status" role="status"></p><ul id="items"></ul>
</main><script>
const headers = { authorization: 'Bearer fixture-token', 'content-type': 'application/json' };
async function load() {
  const response = await fetch('/items', { headers });
  if (!response.ok) throw new Error('Could not load items');
  const items = await response.json();
  document.querySelector('#items').replaceChildren(...items.map(value => {
    const item = document.createElement('li'); item.textContent = value; return item;
  }));
}
document.querySelector('form').addEventListener('submit', async event => {
  event.preventDefault();
  const status = document.querySelector('#status'); status.textContent = 'Saving';
  try {
    const response = await fetch('/items', { method: 'POST', headers,
      body: JSON.stringify({ value: document.querySelector('#value').value }) });
    if (!response.ok) throw new Error('Save failed');
    await load(); status.textContent = 'Saved';
  } catch (error) { status.textContent = error.message; }
});
load().catch(error => { document.querySelector('#status').textContent = error.message; });
</script></body></html>`;
