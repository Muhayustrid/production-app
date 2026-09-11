import { createRouter, createWebHistory } from "vue-router";

import { getCookie } from "@/lib/cookies";

const routes = [
	{
		path: "/",
		name: "WorkOrderList",
		component: () => import("@/pages/WorkOrderList.vue"),
	},
	{
		path: "/work-orders/:name",
		name: "WorkOrderDetail",
		component: () => import("@/pages/WorkOrderDetail.vue"),
		props: true,
	},
	// SPA catch-all: any other /production-app/* deep link falls back to the
	// list screen (unknown WO names render the detail's error state).
	{
		path: "/:pathMatch(.*)*",
		redirect: "/",
	},
];

const router = createRouter({
	history: createWebHistory("/production-app"),
	routes,
});

// Login gate: same pattern as pos_next (session cookie check in a router
// guard); guests are sent to the core login page. The www page itself is
// publicly served — the SPA content is what is gated.
router.beforeEach((to, from, next) => {
	const user = getCookie("user_id");
	if (!user || user === "Guest") {
		window.location.href = "/login?redirect-to=/production-app";
		return;
	}
	next();
});

export default router;
