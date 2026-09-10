import { createRouter, createWebHistory } from "vue-router";

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
];

const router = createRouter({
	history: createWebHistory("/production-app"),
	routes,
});

// Login gate: same pattern as pos_next (session cookie check in a router
// guard); guests are sent to the core login page. The www page itself is
// publicly served — the SPA content is what is gated.
router.beforeEach((to, from, next) => {
	const cookies = new URLSearchParams(document.cookie.split("; ").join("&"));
	const user = cookies.get("user_id");
	if (!user || user === "Guest") {
		window.location.href = "/login?redirect-to=/production-app";
		return;
	}
	next();
});

export default router;
