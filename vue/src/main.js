import { createApp } from "vue";

import App from "./App.vue";
import router from "./router";
import { NEEDS_ALLOWANCE, STATE_CHANGED, setApiErrorHandler } from "./api/client";
import { showToast } from "./composables/toast";
import { reloadCurrentDetail } from "./stores/workOrders";

import "./index.css";

// Central error surface (spec 9.3): every api error is toasted once here;
// STATE_CHANGED additionally reloads the current detail so the operator is
// looking at the winning state (10.1). NEEDS_ALLOWANCE keeps the server's
// Indonesian guidance text.
setApiErrorHandler((error) => {
	if (error.code === STATE_CHANGED) {
		showToast("Data berubah di server - detail dimuat ulang.", "warning");
		reloadCurrentDetail();
	} else if (error.code === NEEDS_ALLOWANCE) {
		showToast(error.message, "warning");
	} else {
		showToast(error.message, "error");
	}
});

createApp(App).use(router).mount("#app");
