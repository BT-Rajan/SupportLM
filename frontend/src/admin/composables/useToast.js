import { reactive } from "vue";

const toasts = reactive([]);
let nextId = 1;

export function useToast() {
  function push(message, kind = "info", timeout = 4000) {
    const id = nextId++;
    toasts.push({ id, message, kind });
    if (timeout) setTimeout(() => dismiss(id), timeout);
    return id;
  }
  function dismiss(id) {
    const idx = toasts.findIndex((t) => t.id === id);
    if (idx !== -1) toasts.splice(idx, 1);
  }
  return {
    toasts,
    success: (msg) => push(msg, "success"),
    error: (msg) => push(msg, "error"),
    info: (msg) => push(msg, "info"),
    dismiss,
  };
}
