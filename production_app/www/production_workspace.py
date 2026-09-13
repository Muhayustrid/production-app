import frappe


def get_context(context):
	# internal workspace: require a logged-in session
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/production_workspace"
		raise frappe.Redirect
	context.no_cache = 1
	return context
