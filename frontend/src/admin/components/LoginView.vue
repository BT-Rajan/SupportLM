<template>
  <div class="auth-shell">
    <div class="auth-card">
      <p class="auth-title">Admin sign in</p>
      <form class="auth-form" @submit.prevent="submit">
        <input v-model="email" class="field-input" type="email" placeholder="Email" autocomplete="username" required>
        <input v-model="password" class="field-input" type="password" placeholder="Password" autocomplete="current-password" required>
        <button type="submit" class="btn-primary" :disabled="submitting">{{ submitting ? "Signing in…" : "Log in" }}</button>
      </form>
      <p v-if="error" class="field-error">{{ error }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { useAdminApi, ApiError } from "../composables/useAdminApi.js";

const props = defineProps({ tenantSlug: { type: String, required: true } });
const emit = defineEmits(["logged-in"]);

const { api } = useAdminApi(props.tenantSlug);
const email = ref("");
const password = ref("");
const error = ref("");
const submitting = ref(false);

async function submit() {
  submitting.value = true;
  error.value = "";
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: email.value, password: password.value }),
    });
    emit("logged-in");
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : "Could not reach the server.";
  } finally {
    submitting.value = false;
  }
}
</script>
