import frappe


def get_context(context):
	# internal workspace: require a logged-in session
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/production_workspace"
		raise frappe.Redirect
	from frappe.sessions import get_csrf_token
	context.csrf_token = get_csrf_token()
	context.workspace_user = frappe.get_cached_value("User", frappe.session.user, "full_name") or frappe.session.user
	context.no_cache = 1
	return context
