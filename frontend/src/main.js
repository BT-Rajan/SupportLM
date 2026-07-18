import { createApp } from "vue";
import App from "./App.vue";
import "./styles/tokens.css";

// templates/chat.html sets window.__SUPPORTLM_CONFIG__ before this
// script loads (same spot the old chat.js read window.TENANT_SLUG
// from). Theme fields (display_name, monogram, logo_url, agent_name)
// are already resolved server-side by resolve_theme() — this app
// renders them, it doesn't re-derive them.
const config = window.__SUPPORTLM_CONFIG__ || {};

createApp(App, { config }).mount("#app");
