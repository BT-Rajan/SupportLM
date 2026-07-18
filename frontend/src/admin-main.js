import { createApp } from "vue";
import AdminApp from "./AdminApp.vue";
import "./styles/tokens.css";
import "./admin/styles/admin.css";

const config = window.__SUPPORTLM_ADMIN_CONFIG__ || {};

createApp(AdminApp, { config }).mount("#admin-app");
