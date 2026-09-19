import { createApp } from "./app.js";
const app = createApp(document);
app.init();
setInterval(() => {
  if (!app.isBusy()) app.refresh();
}, 5000);
