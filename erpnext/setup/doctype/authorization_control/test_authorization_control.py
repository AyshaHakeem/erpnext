# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe

from erpnext.tests.utils import ERPNextTestSuite


class TestAuthorizationControl(ERPNextTestSuite):
	def test_itemwise_rule_honors_role_scope_and_default_company(self):
		approver_role = "_Test Item Approver Role"
		if not frappe.db.exists("Role", approver_role):
			frappe.get_doc({"doctype": "Role", "role_name": approver_role}).insert()

		user = "_test_item_auth_control_user@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user,
					"first_name": "Item Auth Control",
					"send_welcome_email": 0,
					"roles": [{"role": "Sales User"}],
				}
			).insert(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "Authorization Rule",
				"transaction": "Sales Order",
				"based_on": "Itemwise Discount",
				"customer_or_item": "Item",
				"master_name": "_Test Item",
				"system_role": "Sales User",
				"value": 10,
				"approving_role": approver_role,
			}
		).insert()

		sales_order = frappe._dict(
			doctype="Sales Order",
			discount_amount=0,
			items=[
				frappe._dict(
					item_code="_Test Item",
					item_group="_Test Item Group",
					qty=1,
					base_price_list_rate=100,
					base_rate=80,
					discount_percentage=20,
				)
			],
		)

		controller = frappe.get_cached_doc("Authorization Control")
		with self.set_user(user):
			self.assertRaises(
				frappe.ValidationError,
				controller.validate_approving_authority,
				"Sales Order",
				"_Test Company",
				80,
				sales_order,
			)

	def test_validate_approving_authority_raises_when_over_limit(self):
		# Exercises validate_approving_authority -> the based_on query-builder lookups and the
		# coalesce()-based rule lookups (formerly ifnull, which is invalid on Postgres).
		if not frappe.db.exists("Role", "_Test Approver Role"):
			frappe.get_doc({"doctype": "Role", "role_name": "_Test Approver Role"}).insert()

		# Run as a non-admin user without the approving role; Administrator implicitly holds every
		# role, so the not-authorized branch would never fire as Administrator.
		user = "_test_auth_control_user@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user,
					"first_name": "Auth Control",
					"send_welcome_email": 0,
					"roles": [{"role": "Sales User"}],
				}
			).insert(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "Authorization Rule",
				"transaction": "Sales Order",
				"based_on": "Grand Total",
				"company": "_Test Company",
				"value": 1000,
				"approving_role": "_Test Approver Role",
			}
		).insert()

		controller = frappe.get_cached_doc("Authorization Control")
		# User lacks _Test Approver Role and the total exceeds the rule value -> not authorized.
		with self.set_user(user):
			self.assertRaises(
				frappe.ValidationError,
				controller.validate_approving_authority,
				"Sales Order",
				"_Test Company",
				5000,
			)

	def test_get_value_based_rule_runs(self):
		# Exercises the four query-builder lookups (incl. the Employee designation subquery) added in
		# get_value_based_rule; with no matching rule they must run and return empty on both engines.
		controller = frappe.get_cached_doc("Authorization Control")
		result = controller.get_value_based_rule("Expense Claim", "_NONEXISTENT-EMP", 100, "_Test Company")
		self.assertEqual(list(result), [])
