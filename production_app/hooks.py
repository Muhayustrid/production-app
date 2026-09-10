app_name = "production_app"
app_title = "Production App"
app_publisher = "Rotiri Project"
app_description = "ERPNext manufacturing proxy app: one-page production terminal for Work Orders (packing sessions, material actuals, idempotent mutations)."
app_email = "rotiropi@users.noreply.github.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext"]

# Fixtures
# --------
# Custom fields on Stock Entry are app-owned (spec section 8); the Work Order
# summary fields are site-owned and deliberately NOT exported (spec 8.3).

CUSTOM_P_FIELDS = [
	"custom_p_good_qty",
	"custom_p_reject_qty",
	"custom_p_trial_qty",
	"custom_p_sisa_qty",
	"custom_p_good_qty_pre",
	"custom_p_reject_qty_pre",
	"custom_p_trial_qty_pre",
	"custom_p_sisa_qty_pre",
	"custom_p_petugas_packing",
	"custom_p_packing_note",
]

PRODUCTION_ROLES = ["Production Operator", "Production Supervisor"]

fixtures = [
	{
		"dt": "Custom Field",
		"filters": [["dt", "=", "Stock Entry"], ["fieldname", "in", CUSTOM_P_FIELDS]],
	},
	{"dt": "Role", "filters": [["role_name", "in", PRODUCTION_ROLES]]},
	{"dt": "Custom DocPerm", "filters": [["role", "in", PRODUCTION_ROLES]]},
]

# DocEvents
# ---------
# Keep the Work Order packing summary in sync on every submit/cancel of a
# manufacturing stock entry - including entries made from Desk without the
# custom_p_* fields (spec 8.1).

doc_events = {
	"Stock Entry": {
		"on_submit": "production_app.wo_summary.on_submit",
		"on_cancel": "production_app.wo_summary.on_cancel",
	}
}

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "production_app",
# 		"logo": "/assets/production_app/logo.png",
# 		"title": "Production App",
# 		"route": "/production_app",
# 		"has_permission": "production_app.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/production_app/css/production_app.css"
# app_include_js = "/assets/production_app/js/production_app.js"

# include js, css files in header of web template
# web_include_css = "/assets/production_app/css/production_app.css"
# web_include_js = "/assets/production_app/js/production_app.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "production_app/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "production_app/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "production_app.utils.jinja_methods",
# 	"filters": "production_app.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "production_app.install.before_install"
# after_install = "production_app.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "production_app.uninstall.before_uninstall"
# after_uninstall = "production_app.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "production_app.utils.before_app_install"
# after_app_install = "production_app.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "production_app.utils.before_app_uninstall"
# after_app_uninstall = "production_app.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "production_app.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "production_app.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["production_app.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"production_app.tasks.all"
# 	],
# 	"daily": [
# 		"production_app.tasks.daily"
# 	],
# 	"hourly": [
# 		"production_app.tasks.hourly"
# 	],
# 	"weekly": [
# 		"production_app.tasks.weekly"
# 	],
# 	"monthly": [
# 		"production_app.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "production_app.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "production_app.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "production_app.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "production_app.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["production_app.utils.before_request"]
# after_request = ["production_app.utils.after_request"]

# Job Events
# ----------
# before_job = ["production_app.utils.before_job"]
# after_job = ["production_app.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"production_app.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

